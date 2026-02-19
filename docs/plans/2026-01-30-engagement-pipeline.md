# Engagement Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Kanban-style engagement tracking board for managing top-of-funnel relationships with DoD stakeholders.

**Architecture:** New SQLite table `engagements` stores operational data (not synced to Obsidian vault). FastAPI endpoints provide CRUD operations. React frontend with three-panel Kanban layout using drag-and-drop. Zustand store for optimistic UI updates.

**Tech Stack:** FastAPI, SQLite, React, TanStack Query, Zustand, @dnd-kit/core for drag-and-drop, Tailwind CSS

---

## Task 1: Create Engagements Database Table

**Files:**
- Modify: `backend/api/main.py` (add table creation in startup)

**Step 1: Add table creation SQL to startup**

In `backend/api/main.py`, after the `db = SQLiteStore(str(db_path))` line (around line 45), add a function to ensure the engagements table exists:

```python
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
```

**Step 2: Call table creation in startup event**

In the `startup()` function (around line 150), add at the beginning:

```python
@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    global _entities_cache

    # Ensure engagements table exists
    _ensure_engagements_table()

    # ... rest of existing code
```

**Step 3: Verify table creation**

Run: `cd backend && python -c "from api.main import _ensure_engagements_table; _ensure_engagements_table(); print('Table created')"`

Expected: "Table created" with no errors

**Step 4: Commit**

```bash
git add backend/api/main.py
git commit -m "feat(backend): add engagements table schema

Creates SQLite table for tracking engagement pipeline data.
Includes indexes on entity_id and stage for query performance."
```

---

## Task 2: Add Engagement API Endpoints

**Files:**
- Modify: `backend/api/main.py` (add 6 new endpoints)

**Step 1: Add Pydantic models for engagements**

Add these imports at the top of main.py with other imports:

```python
from pydantic import BaseModel
from datetime import datetime
import uuid
```

Add these models after the existing imports section (around line 30):

```python
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
```

**Step 2: Add helper function to get engagement with entity data**

Add this helper function (can go near other helper functions, around line 125):

```python
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
```

**Step 3: Add GET /api/engagements/board endpoint**

Add this endpoint (can go at end of file before if __name__ block):

```python
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

    # Build query with filters
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

    query += " ORDER BY updated_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    # Build entity lookup from cache
    entities_by_id = {e.id: e for e in _entities_cache}

    # Convert to response format with filtering
    engagements = []
    for row in rows:
        eng = _get_engagement_with_entity(row, entities_by_id)

        # Apply service filter (needs entity data)
        if service:
            services = [s.strip() for s in service.split(",")]
            if eng["entity_service"] not in services:
                continue

        # Apply search filter
        if search:
            if search.lower() not in eng["entity_name"].lower():
                continue

        engagements.append(eng)

    # Define stages for response
    stages = ["targeted", "outreach", "engaged", "warm", "on_contract", "on_ice"]

    return {
        "engagements": engagements,
        "stages": stages,
        "stats": {
            stage: len([e for e in engagements if e["stage"] == stage])
            for stage in stages
        }
    }
```

**Step 4: Add POST /api/engagements endpoint**

```python
@app.post("/api/engagements")
async def create_engagement(engagement: EngagementCreate):
    """Create a new engagement."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    # Check if engagement already exists for this entity
    existing = conn.execute(
        "SELECT id FROM engagements WHERE entity_id = ?",
        (engagement.entity_id,)
    ).fetchone()

    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Engagement already exists for this entity")

    # Verify entity exists
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
```

**Step 5: Add PUT /api/engagements/{id} endpoint**

```python
@app.put("/api/engagements/{engagement_id}")
async def update_engagement(engagement_id: str, update: EngagementUpdate):
    """Update an engagement."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    # Check engagement exists
    existing = conn.execute(
        "SELECT entity_id FROM engagements WHERE id = ?",
        (engagement_id,)
    ).fetchone()

    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Engagement not found")

    # Build update query dynamically
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

    # Fetch updated record
    row = conn.execute(
        "SELECT id, entity_id, entity_type, stage, priority, notes, created_at, updated_at FROM engagements WHERE id = ?",
        (engagement_id,)
    ).fetchone()
    conn.close()

    entities_by_id = {e.id: e for e in _entities_cache}
    return _get_engagement_with_entity(row, entities_by_id)
```

**Step 6: Add PATCH /api/engagements/{id}/stage endpoint (for drag-drop)**

```python
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
```

**Step 7: Add DELETE /api/engagements/{id} endpoint**

```python
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
```

**Step 8: Add GET /api/engagements/stats endpoint**

```python
@app.get("/api/engagements/stats")
async def get_engagement_stats():
    """Get pipeline metrics."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    stages = ["targeted", "outreach", "engaged", "warm", "on_contract", "on_ice"]

    # Count by stage
    by_stage = {}
    for stage in stages:
        count = conn.execute(
            "SELECT COUNT(*) FROM engagements WHERE stage = ?",
            (stage,)
        ).fetchone()[0]
        by_stage[stage] = count

    # Count by priority
    by_priority = {}
    for priority in ["critical", "high", "medium", "low"]:
        count = conn.execute(
            "SELECT COUNT(*) FROM engagements WHERE priority = ?",
            (priority,)
        ).fetchone()[0]
        by_priority[priority] = count

    # Count by entity type
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
```

**Step 9: Test endpoints manually**

Run backend: `cd backend && python -m uvicorn api.main:app --reload --port 8000`

Test with curl:
```bash
# Test board endpoint
curl http://localhost:8000/api/engagements/board

# Test stats endpoint
curl http://localhost:8000/api/engagements/stats
```

Expected: JSON responses with empty arrays/zero counts

**Step 10: Commit**

```bash
git add backend/api/main.py
git commit -m "feat(backend): add engagement pipeline API endpoints

- GET /api/engagements/board - fetch all engagements with entity data
- POST /api/engagements - create new engagement
- PUT /api/engagements/{id} - update engagement
- PATCH /api/engagements/{id}/stage - quick stage update for drag-drop
- DELETE /api/engagements/{id} - remove engagement
- GET /api/engagements/stats - pipeline metrics"
```

---

## Task 3: Add Entity Search Endpoint for Quick-Add

**Files:**
- Modify: `backend/api/main.py`

**Step 1: Add entity autocomplete endpoint**

This endpoint enables the quick-add search functionality:

```python
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
            # Check if already has an engagement
            results.append({
                "id": entity.id,
                "title": entity.title,
                "entity_type": entity.entity_type,
                "service": entity.service,
            })

            if len(results) >= limit:
                break

    return {"results": results}
```

**Step 2: Test autocomplete**

```bash
curl "http://localhost:8000/api/entities/autocomplete?q=army"
```

Expected: JSON with matching entities

**Step 3: Commit**

```bash
git add backend/api/main.py
git commit -m "feat(backend): add entity autocomplete endpoint for engagement quick-add"
```

---

## Task 4: Add Frontend API Hooks

**Files:**
- Modify: `frontend/src/hooks/useApi.ts`

**Step 1: Add engagement types**

Add these types after the existing type definitions (around line 1030):

```typescript
// =============================================================================
// Engagement Pipeline Types and Hooks
// =============================================================================

export interface Engagement {
  id: string;
  entity_id: string;
  entity_type: string;
  entity_name: string;
  entity_service: string | null;
  stage: string;
  priority: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface EngagementBoardResponse {
  engagements: Engagement[];
  stages: string[];
  stats: Record<string, number>;
}

export interface EngagementCreate {
  entity_id: string;
  entity_type: string;
  stage?: string;
  priority?: string;
  notes?: string;
}

export interface EngagementUpdate {
  stage?: string;
  priority?: string;
  notes?: string;
}

export interface EntityAutocompleteResult {
  id: string;
  title: string;
  entity_type: string;
  service: string | null;
}

export interface EntityAutocompleteResponse {
  results: EntityAutocompleteResult[];
}

export interface EngagementStats {
  total: number;
  by_stage: Record<string, number>;
  by_priority: Record<string, number>;
  by_entity_type: Record<string, number>;
}
```

**Step 2: Add useEngagementBoard hook**

```typescript
export function useEngagementBoard(filters?: {
  entityType?: string[];
  service?: string[];
  priority?: string[];
  search?: string;
}) {
  const params = new URLSearchParams();
  if (filters?.entityType?.length) params.set('entity_type', filters.entityType.join(','));
  if (filters?.service?.length) params.set('service', filters.service.join(','));
  if (filters?.priority?.length) params.set('priority', filters.priority.join(','));
  if (filters?.search) params.set('search', filters.search);

  return useQuery<EngagementBoardResponse>({
    queryKey: ['engagements-board', filters],
    queryFn: () => fetchJson(`/engagements/board?${params}`),
  });
}
```

**Step 3: Add engagement mutation hooks**

```typescript
export function useCreateEngagement() {
  const queryClient = useQueryClient();

  return useMutation<Engagement, Error, EngagementCreate>({
    mutationFn: async (data) => {
      const response = await fetch(`${API_BASE}/engagements`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Create failed: ${response.status}`);
      }
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['engagements-board'] });
      queryClient.invalidateQueries({ queryKey: ['engagements-stats'] });
    },
  });
}

export function useUpdateEngagement() {
  const queryClient = useQueryClient();

  return useMutation<Engagement, Error, { id: string; update: EngagementUpdate }>({
    mutationFn: async ({ id, update }) => {
      const response = await fetch(`${API_BASE}/engagements/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(update),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Update failed: ${response.status}`);
      }
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['engagements-board'] });
      queryClient.invalidateQueries({ queryKey: ['engagements-stats'] });
    },
  });
}

export function useUpdateEngagementStage() {
  const queryClient = useQueryClient();

  return useMutation<Engagement, Error, { id: string; stage: string }>({
    mutationFn: async ({ id, stage }) => {
      const response = await fetch(`${API_BASE}/engagements/${id}/stage`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Update failed: ${response.status}`);
      }
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['engagements-board'] });
      queryClient.invalidateQueries({ queryKey: ['engagements-stats'] });
    },
  });
}

export function useDeleteEngagement() {
  const queryClient = useQueryClient();

  return useMutation<{ success: boolean; id: string }, Error, string>({
    mutationFn: async (id) => {
      const response = await fetch(`${API_BASE}/engagements/${id}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        throw new Error(`Delete failed: ${response.status}`);
      }
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['engagements-board'] });
      queryClient.invalidateQueries({ queryKey: ['engagements-stats'] });
    },
  });
}
```

**Step 4: Add entity autocomplete hook**

```typescript
export function useEntityAutocomplete(query: string, types?: string[]) {
  const params = new URLSearchParams({ q: query });
  if (types?.length) params.set('types', types.join(','));

  return useQuery<EntityAutocompleteResponse>({
    queryKey: ['entity-autocomplete', query, types],
    queryFn: () => fetchJson(`/entities/autocomplete?${params}`),
    enabled: query.length >= 2,
  });
}

export function useEngagementStats() {
  return useQuery<EngagementStats>({
    queryKey: ['engagements-stats'],
    queryFn: () => fetchJson('/engagements/stats'),
  });
}
```

**Step 5: Verify TypeScript compiles**

Run: `cd frontend && npm run build`

Expected: Build succeeds with no type errors

**Step 6: Commit**

```bash
git add frontend/src/hooks/useApi.ts
git commit -m "feat(frontend): add engagement pipeline API hooks

- useEngagementBoard - fetch board data with filters
- useCreateEngagement - create new engagement
- useUpdateEngagement - update engagement details
- useUpdateEngagementStage - quick stage update for drag-drop
- useDeleteEngagement - remove engagement
- useEntityAutocomplete - search entities for quick-add
- useEngagementStats - pipeline metrics"
```

---

## Task 5: Install dnd-kit for Drag-and-Drop

**Files:**
- Modify: `frontend/package.json`

**Step 1: Install dnd-kit packages**

```bash
cd frontend && npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
```

**Step 2: Verify installation**

Run: `cd frontend && npm run build`

Expected: Build succeeds

**Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore(frontend): add @dnd-kit for kanban drag-and-drop"
```

---

## Task 6: Create Engagement Pipeline View

**Files:**
- Create: `frontend/src/views/EngagementPipeline.tsx`

**Step 1: Create the main view file**

```typescript
import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
} from '@dnd-kit/core'
import { Loader2, Plus, Search, X } from 'lucide-react'
import {
  useEngagementBoard,
  useUpdateEngagementStage,
  useCreateEngagement,
  useDeleteEngagement,
  useEntityAutocomplete,
  type Engagement,
  type EntityAutocompleteResult,
} from '../hooks/useApi'
import FilterChips from '../components/FilterChips'
import clsx from 'clsx'

// Stage configuration
const STAGES = [
  { id: 'targeted', label: 'Targeted', description: 'On radar, prioritized' },
  { id: 'outreach', label: 'Outreach', description: 'Initial contact made' },
  { id: 'engaged', label: 'Engaged', description: 'Active dialogue' },
  { id: 'warm', label: 'Warm', description: 'Strong relationship' },
  { id: 'on_contract', label: 'On Contract', description: 'Active business' },
  { id: 'on_ice', label: 'On Ice', description: 'Gone cold' },
]

const PRIORITIES = ['critical', 'high', 'medium', 'low']
const ENTITY_TYPES = ['stakeholder', 'unit', 'congress_member', 'executive_official']

const PRIORITY_COLORS: Record<string, string> = {
  critical: 'border-l-red-500',
  high: 'border-l-amber-500',
  medium: 'border-l-blue-500',
  low: 'border-l-gray-500',
}

export default function EngagementPipeline() {
  const [entityTypeFilter, setEntityTypeFilter] = useState<string[]>([])
  const [serviceFilter, setServiceFilter] = useState<string[]>([])
  const [priorityFilter, setPriorityFilter] = useState<string[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedEngagement, setSelectedEngagement] = useState<Engagement | null>(null)
  const [showQuickAdd, setShowQuickAdd] = useState(false)
  const [activeId, setActiveId] = useState<string | null>(null)

  const { data, isLoading } = useEngagementBoard({
    entityType: entityTypeFilter.length > 0 ? entityTypeFilter : undefined,
    service: serviceFilter.length > 0 ? serviceFilter : undefined,
    priority: priorityFilter.length > 0 ? priorityFilter : undefined,
    search: searchQuery || undefined,
  })

  const updateStageMutation = useUpdateEngagementStage()

  // Group engagements by stage
  const engagementsByStage = useMemo(() => {
    const grouped: Record<string, Engagement[]> = {}
    for (const stage of STAGES) {
      grouped[stage.id] = []
    }
    if (data?.engagements) {
      for (const eng of data.engagements) {
        if (grouped[eng.stage]) {
          grouped[eng.stage].push(eng)
        }
      }
    }
    return grouped
  }, [data?.engagements])

  // DnD sensors
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor)
  )

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    setActiveId(null)

    if (!over) return

    const engagementId = active.id as string
    const newStage = over.id as string

    // Find the engagement
    const engagement = data?.engagements.find((e) => e.id === engagementId)
    if (!engagement || engagement.stage === newStage) return

    // Update stage
    updateStageMutation.mutate({ id: engagementId, stage: newStage })
  }

  const activeEngagement = activeId
    ? data?.engagements.find((e) => e.id === activeId)
    : null

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 text-accent-primary animate-spin" />
      </div>
    )
  }

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Engagement Pipeline</h1>
          <p className="text-text-secondary text-sm">
            Track relationships with DoD stakeholders
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" />
            <input
              type="text"
              placeholder="Search entities..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-3 py-1.5 w-48 bg-bg-secondary border border-border rounded-md text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-accent-primary"
            />
          </div>

          {/* Filters */}
          <FilterChips
            label="Type"
            options={ENTITY_TYPES}
            selected={entityTypeFilter}
            onChange={setEntityTypeFilter}
          />
          <FilterChips
            label="Priority"
            options={PRIORITIES}
            selected={priorityFilter}
            onChange={setPriorityFilter}
          />

          {/* Quick Add Button */}
          <button
            onClick={() => setShowQuickAdd(true)}
            className="flex items-center gap-2 px-3 py-1.5 bg-accent-primary text-text-inverse rounded-md text-sm font-medium hover:bg-accent-primary/90 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add Entity
          </button>
        </div>
      </div>

      {/* Kanban Board */}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="flex-1 flex gap-3 overflow-x-auto pb-4">
          {STAGES.map((stage) => (
            <KanbanColumn
              key={stage.id}
              stage={stage}
              engagements={engagementsByStage[stage.id]}
              count={data?.stats[stage.id] ?? 0}
              onCardClick={setSelectedEngagement}
            />
          ))}
        </div>

        <DragOverlay>
          {activeEngagement && (
            <EngagementCard engagement={activeEngagement} isDragging />
          )}
        </DragOverlay>
      </DndContext>

      {/* Quick Add Modal */}
      {showQuickAdd && (
        <QuickAddModal onClose={() => setShowQuickAdd(false)} />
      )}

      {/* Detail Panel */}
      {selectedEngagement && (
        <DetailPanel
          engagement={selectedEngagement}
          onClose={() => setSelectedEngagement(null)}
        />
      )}
    </div>
  )
}

// Kanban Column Component
function KanbanColumn({
  stage,
  engagements,
  count,
  onCardClick,
}: {
  stage: { id: string; label: string; description: string }
  engagements: Engagement[]
  count: number
  onCardClick: (e: Engagement) => void
}) {
  return (
    <div
      id={stage.id}
      className="flex-shrink-0 w-64 flex flex-col bg-bg-secondary rounded-lg border border-border"
    >
      {/* Column Header */}
      <div className="px-3 py-2 border-b border-border">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text-primary">{stage.label}</h3>
          <span className="text-xs font-mono text-text-tertiary bg-bg-tertiary px-1.5 py-0.5 rounded">
            {count}
          </span>
        </div>
        <p className="text-xs text-text-tertiary mt-0.5">{stage.description}</p>
      </div>

      {/* Cards */}
      <div className="flex-1 p-2 space-y-2 overflow-y-auto min-h-[200px]">
        {engagements.map((eng) => (
          <EngagementCard
            key={eng.id}
            engagement={eng}
            onClick={() => onCardClick(eng)}
          />
        ))}
        {engagements.length === 0 && (
          <div className="text-xs text-text-tertiary text-center py-4">
            Drop cards here
          </div>
        )}
      </div>
    </div>
  )
}

// Engagement Card Component
function EngagementCard({
  engagement,
  onClick,
  isDragging,
}: {
  engagement: Engagement
  onClick?: () => void
  isDragging?: boolean
}) {
  return (
    <div
      id={engagement.id}
      onClick={onClick}
      className={clsx(
        'p-2.5 bg-bg-primary border border-border rounded-md cursor-pointer transition-all',
        'hover:border-accent-primary hover:bg-bg-tertiary',
        'border-l-2',
        PRIORITY_COLORS[engagement.priority] || 'border-l-gray-500',
        isDragging && 'opacity-90 shadow-md rotate-2'
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-medium text-text-primary truncate">
            {engagement.entity_name}
          </h4>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-text-tertiary capitalize">
              {engagement.entity_type.replace('_', ' ')}
            </span>
            {engagement.entity_service && (
              <>
                <span className="text-text-tertiary">·</span>
                <span className="text-xs text-text-tertiary">
                  {engagement.entity_service}
                </span>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// Quick Add Modal
function QuickAddModal({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [selectedEntity, setSelectedEntity] = useState<EntityAutocompleteResult | null>(null)
  const [priority, setPriority] = useState('medium')
  const [notes, setNotes] = useState('')

  const { data: autocompleteData } = useEntityAutocomplete(query, ENTITY_TYPES)
  const createMutation = useCreateEngagement()

  const handleCreate = () => {
    if (!selectedEntity) return

    createMutation.mutate(
      {
        entity_id: selectedEntity.id,
        entity_type: selectedEntity.entity_type,
        priority,
        notes,
      },
      {
        onSuccess: () => {
          onClose()
        },
      }
    )
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-bg-secondary border border-border rounded-lg w-[480px] max-h-[80vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h2 className="text-lg font-semibold text-text-primary">Add to Pipeline</h2>
          <button
            onClick={onClose}
            className="p-1 text-text-secondary hover:text-text-primary rounded"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {/* Entity Search */}
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">
              Search Entity
            </label>
            <input
              type="text"
              placeholder="Type to search..."
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setSelectedEntity(null)
              }}
              className="w-full px-3 py-2 bg-bg-primary border border-border rounded-md text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-accent-primary"
            />

            {/* Autocomplete Results */}
            {query.length >= 2 && !selectedEntity && autocompleteData?.results && (
              <div className="mt-1 max-h-48 overflow-y-auto border border-border rounded-md bg-bg-primary">
                {autocompleteData.results.map((result) => (
                  <button
                    key={result.id}
                    onClick={() => {
                      setSelectedEntity(result)
                      setQuery(result.title)
                    }}
                    className="w-full px-3 py-2 text-left hover:bg-bg-tertiary transition-colors"
                  >
                    <div className="text-sm text-text-primary">{result.title}</div>
                    <div className="text-xs text-text-tertiary">
                      {result.entity_type.replace('_', ' ')}
                      {result.service && ` · ${result.service}`}
                    </div>
                  </button>
                ))}
                {autocompleteData.results.length === 0 && (
                  <div className="px-3 py-2 text-sm text-text-tertiary">
                    No matching entities
                  </div>
                )}
              </div>
            )}

            {/* Selected Entity */}
            {selectedEntity && (
              <div className="mt-2 p-2 bg-accent-primary/10 border border-accent-primary/30 rounded-md">
                <div className="text-sm text-text-primary">{selectedEntity.title}</div>
                <div className="text-xs text-text-secondary">
                  {selectedEntity.entity_type.replace('_', ' ')}
                  {selectedEntity.service && ` · ${selectedEntity.service}`}
                </div>
              </div>
            )}
          </div>

          {/* Priority */}
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">
              Priority
            </label>
            <div className="flex gap-2">
              {PRIORITIES.map((p) => (
                <button
                  key={p}
                  onClick={() => setPriority(p)}
                  className={clsx(
                    'px-3 py-1.5 text-sm rounded-md border transition-colors capitalize',
                    priority === p
                      ? 'bg-accent-primary/10 border-accent-primary text-accent-primary'
                      : 'bg-bg-primary border-border text-text-secondary hover:bg-bg-tertiary'
                  )}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">
              Notes (optional)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Initial notes..."
              rows={3}
              className="w-full px-3 py-2 bg-bg-primary border border-border rounded-md text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-accent-primary resize-none"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-4 py-3 border-t border-border">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!selectedEntity || createMutation.isPending}
            className="px-4 py-2 bg-accent-primary text-text-inverse rounded-md text-sm font-medium hover:bg-accent-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {createMutation.isPending ? 'Adding...' : 'Add to Pipeline'}
          </button>
        </div>
      </div>
    </div>
  )
}

// Detail Panel
function DetailPanel({
  engagement,
  onClose,
}: {
  engagement: Engagement
  onClose: () => void
}) {
  const deleteMutation = useDeleteEngagement()

  const handleDelete = () => {
    if (confirm('Remove this engagement from the pipeline?')) {
      deleteMutation.mutate(engagement.id, {
        onSuccess: () => onClose(),
      })
    }
  }

  return (
    <div className="fixed right-0 top-0 h-full w-96 bg-bg-secondary border-l border-border shadow-lg z-40 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h2 className="text-lg font-semibold text-text-primary truncate">
          {engagement.entity_name}
        </h2>
        <button
          onClick={onClose}
          className="p-1 text-text-secondary hover:text-text-primary rounded"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Entity Info */}
        <div>
          <Link
            to={`/entity/${engagement.entity_id}`}
            className="text-sm text-accent-primary hover:underline"
          >
            View Entity Details →
          </Link>
        </div>

        {/* Metadata */}
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-text-tertiary">Type</span>
            <span className="text-text-primary capitalize">
              {engagement.entity_type.replace('_', ' ')}
            </span>
          </div>
          {engagement.entity_service && (
            <div className="flex justify-between text-sm">
              <span className="text-text-tertiary">Service</span>
              <span className="text-text-primary">{engagement.entity_service}</span>
            </div>
          )}
          <div className="flex justify-between text-sm">
            <span className="text-text-tertiary">Stage</span>
            <span className="text-text-primary capitalize">
              {engagement.stage.replace('_', ' ')}
            </span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-text-tertiary">Priority</span>
            <span className="text-text-primary capitalize">{engagement.priority}</span>
          </div>
        </div>

        {/* Notes */}
        <div>
          <h3 className="text-sm font-medium text-text-secondary mb-1">Notes</h3>
          <p className="text-sm text-text-primary whitespace-pre-wrap">
            {engagement.notes || 'No notes yet.'}
          </p>
        </div>

        {/* Timestamps */}
        <div className="pt-4 border-t border-border space-y-1">
          <div className="text-xs text-text-tertiary">
            Created: {new Date(engagement.created_at).toLocaleDateString()}
          </div>
          <div className="text-xs text-text-tertiary">
            Updated: {new Date(engagement.updated_at).toLocaleDateString()}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-border">
        <button
          onClick={handleDelete}
          disabled={deleteMutation.isPending}
          className="w-full px-4 py-2 text-sm text-red-400 hover:bg-red-500/10 rounded-md transition-colors"
        >
          {deleteMutation.isPending ? 'Removing...' : 'Remove from Pipeline'}
        </button>
      </div>
    </div>
  )
}
```

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npm run build`

Expected: Build succeeds

**Step 3: Commit**

```bash
git add frontend/src/views/EngagementPipeline.tsx
git commit -m "feat(frontend): create Engagement Pipeline view

Three-panel Kanban board with:
- Drag-and-drop stage management via @dnd-kit
- Entity search/autocomplete for quick-add
- Filters by entity type, service, priority
- Detail panel for viewing engagement info
- Delete functionality"
```

---

## Task 7: Add Draggable Card Support with dnd-kit

**Files:**
- Modify: `frontend/src/views/EngagementPipeline.tsx`

**Step 1: Add useDraggable to EngagementCard**

Update the imports at the top of EngagementPipeline.tsx:

```typescript
import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  useDroppable,
  useDraggable,
  type DragStartEvent,
  type DragEndEvent,
} from '@dnd-kit/core'
```

**Step 2: Update KanbanColumn to be droppable**

Replace the KanbanColumn function with:

```typescript
function KanbanColumn({
  stage,
  engagements,
  count,
  onCardClick,
}: {
  stage: { id: string; label: string; description: string }
  engagements: Engagement[]
  count: number
  onCardClick: (e: Engagement) => void
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: stage.id,
  })

  return (
    <div
      ref={setNodeRef}
      className={clsx(
        'flex-shrink-0 w-64 flex flex-col bg-bg-secondary rounded-lg border transition-colors',
        isOver ? 'border-accent-primary bg-accent-primary/5' : 'border-border'
      )}
    >
      {/* Column Header */}
      <div className="px-3 py-2 border-b border-border">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text-primary">{stage.label}</h3>
          <span className="text-xs font-mono text-text-tertiary bg-bg-tertiary px-1.5 py-0.5 rounded">
            {count}
          </span>
        </div>
        <p className="text-xs text-text-tertiary mt-0.5">{stage.description}</p>
      </div>

      {/* Cards */}
      <div className="flex-1 p-2 space-y-2 overflow-y-auto min-h-[200px]">
        {engagements.map((eng) => (
          <DraggableCard
            key={eng.id}
            engagement={eng}
            onClick={() => onCardClick(eng)}
          />
        ))}
        {engagements.length === 0 && (
          <div className="text-xs text-text-tertiary text-center py-4">
            Drop cards here
          </div>
        )}
      </div>
    </div>
  )
}
```

**Step 3: Create DraggableCard wrapper component**

Add this component after KanbanColumn:

```typescript
function DraggableCard({
  engagement,
  onClick,
}: {
  engagement: Engagement
  onClick: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: engagement.id,
  })

  const style = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
      }
    : undefined

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={clsx(isDragging && 'opacity-50')}
    >
      <EngagementCard engagement={engagement} onClick={onClick} />
    </div>
  )
}
```

**Step 4: Update EngagementCard to not have drag logic**

Update EngagementCard to be a pure presentational component:

```typescript
function EngagementCard({
  engagement,
  onClick,
  isDragging,
}: {
  engagement: Engagement
  onClick?: () => void
  isDragging?: boolean
}) {
  return (
    <div
      onClick={onClick}
      className={clsx(
        'p-2.5 bg-bg-primary border border-border rounded-md cursor-pointer transition-all',
        'hover:border-accent-primary hover:bg-bg-tertiary',
        'border-l-2',
        PRIORITY_COLORS[engagement.priority] || 'border-l-gray-500',
        isDragging && 'opacity-90 shadow-md rotate-2 scale-105'
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-medium text-text-primary truncate">
            {engagement.entity_name}
          </h4>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-text-tertiary capitalize">
              {engagement.entity_type.replace('_', ' ')}
            </span>
            {engagement.entity_service && (
              <>
                <span className="text-text-tertiary">·</span>
                <span className="text-xs text-text-tertiary">
                  {engagement.entity_service}
                </span>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
```

**Step 5: Verify drag-and-drop works**

Run: `cd frontend && npm run dev`

Test: Open http://localhost:5173/pipeline, add an entity, drag between columns

Expected: Cards drag smoothly, columns highlight on hover, stage updates on drop

**Step 6: Commit**

```bash
git add frontend/src/views/EngagementPipeline.tsx
git commit -m "feat(frontend): add drag-and-drop support to engagement cards

- useDraggable hook on cards for drag behavior
- useDroppable on columns for drop targets
- Visual feedback on drag (opacity, scale)
- Column highlight when dragging over"
```

---

## Task 8: Add Routes and Navigation

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`

**Step 1: Add route to App.tsx**

Add import at top:

```typescript
import EngagementPipeline from './views/EngagementPipeline'
```

Add route inside the `<Route path="/" element={<Layout />}>` block, after the news route:

```typescript
<Route path="pipeline" element={<EngagementPipeline />} />
```

**Step 2: Add navigation link to Layout.tsx**

Add import for the icon:

```typescript
import {
  Search,
  Users,
  Target,
  Radio,
  Ship,
  FileText,
  Landmark,
  UsersRound,
  ChevronRight,
  Rss,
  Kanban,  // Add this
} from 'lucide-react'
```

Add to the navigation array after News:

```typescript
const navigation = [
  { name: 'Explorer', href: '/explore', icon: Search },
  { name: 'Units', href: '/units', icon: Users },
  { name: 'Programs', href: '/programs', icon: FileText },
  { name: 'Platforms', href: '/platforms', icon: Ship },
  { name: 'Technology', href: '/technology', icon: Radio },
  { name: 'Stakeholders', href: '/stakeholders', icon: UsersRound },
  { name: 'Political Affairs', href: '/political-affairs', icon: Landmark },
  { name: 'Companies', href: '/companies', icon: Target },
  { name: 'News', href: '/news', icon: Rss },
  { name: 'Pipeline', href: '/pipeline', icon: Kanban },  // Add this
]
```

**Step 3: Verify navigation works**

Run: `cd frontend && npm run dev`

Test: Click "Pipeline" in sidebar navigation

Expected: Navigates to /pipeline, shows Engagement Pipeline view

**Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/Layout.tsx
git commit -m "feat(frontend): add Pipeline route and navigation

- Add /pipeline route pointing to EngagementPipeline view
- Add Pipeline link to sidebar with Kanban icon"
```

---

## Task 9: Add Edit Functionality to Detail Panel

**Files:**
- Modify: `frontend/src/views/EngagementPipeline.tsx`

**Step 1: Add edit state and mutation to DetailPanel**

Update the DetailPanel component to include edit functionality:

```typescript
function DetailPanel({
  engagement,
  onClose,
}: {
  engagement: Engagement
  onClose: () => void
}) {
  const [isEditing, setIsEditing] = useState(false)
  const [editStage, setEditStage] = useState(engagement.stage)
  const [editPriority, setEditPriority] = useState(engagement.priority)
  const [editNotes, setEditNotes] = useState(engagement.notes)

  const updateMutation = useUpdateEngagement()
  const deleteMutation = useDeleteEngagement()

  // Reset edit state when engagement changes
  useEffect(() => {
    setEditStage(engagement.stage)
    setEditPriority(engagement.priority)
    setEditNotes(engagement.notes)
    setIsEditing(false)
  }, [engagement])

  const handleSave = () => {
    updateMutation.mutate(
      {
        id: engagement.id,
        update: {
          stage: editStage,
          priority: editPriority,
          notes: editNotes,
        },
      },
      {
        onSuccess: () => {
          setIsEditing(false)
        },
      }
    )
  }

  const handleDelete = () => {
    if (confirm('Remove this engagement from the pipeline?')) {
      deleteMutation.mutate(engagement.id, {
        onSuccess: () => onClose(),
      })
    }
  }

  return (
    <div className="fixed right-0 top-0 h-full w-96 bg-bg-secondary border-l border-border shadow-lg z-40 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h2 className="text-lg font-semibold text-text-primary truncate">
          {engagement.entity_name}
        </h2>
        <button
          onClick={onClose}
          className="p-1 text-text-secondary hover:text-text-primary rounded"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Entity Info */}
        <div>
          <Link
            to={`/entity/${engagement.entity_id}`}
            className="text-sm text-accent-primary hover:underline"
          >
            View Entity Details →
          </Link>
        </div>

        {/* Metadata (read-only) */}
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-text-tertiary">Type</span>
            <span className="text-text-primary capitalize">
              {engagement.entity_type.replace('_', ' ')}
            </span>
          </div>
          {engagement.entity_service && (
            <div className="flex justify-between text-sm">
              <span className="text-text-tertiary">Service</span>
              <span className="text-text-primary">{engagement.entity_service}</span>
            </div>
          )}
        </div>

        {/* Editable Fields */}
        {isEditing ? (
          <>
            {/* Stage */}
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">
                Stage
              </label>
              <select
                value={editStage}
                onChange={(e) => setEditStage(e.target.value)}
                className="w-full px-3 py-2 bg-bg-primary border border-border rounded-md text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
              >
                {STAGES.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Priority */}
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">
                Priority
              </label>
              <div className="flex gap-2">
                {PRIORITIES.map((p) => (
                  <button
                    key={p}
                    onClick={() => setEditPriority(p)}
                    className={clsx(
                      'px-3 py-1.5 text-sm rounded-md border transition-colors capitalize',
                      editPriority === p
                        ? 'bg-accent-primary/10 border-accent-primary text-accent-primary'
                        : 'bg-bg-primary border-border text-text-secondary hover:bg-bg-tertiary'
                    )}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>

            {/* Notes */}
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">
                Notes
              </label>
              <textarea
                value={editNotes}
                onChange={(e) => setEditNotes(e.target.value)}
                rows={5}
                className="w-full px-3 py-2 bg-bg-primary border border-border rounded-md text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-primary resize-none"
              />
            </div>

            {/* Save/Cancel buttons */}
            <div className="flex gap-2">
              <button
                onClick={handleSave}
                disabled={updateMutation.isPending}
                className="flex-1 px-4 py-2 bg-accent-primary text-text-inverse rounded-md text-sm font-medium hover:bg-accent-primary/90 transition-colors disabled:opacity-50"
              >
                {updateMutation.isPending ? 'Saving...' : 'Save'}
              </button>
              <button
                onClick={() => setIsEditing(false)}
                className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
              >
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            {/* Display mode */}
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-text-tertiary">Stage</span>
                <span className="text-text-primary capitalize">
                  {engagement.stage.replace('_', ' ')}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-text-tertiary">Priority</span>
                <span className="text-text-primary capitalize">{engagement.priority}</span>
              </div>
            </div>

            {/* Notes */}
            <div>
              <h3 className="text-sm font-medium text-text-secondary mb-1">Notes</h3>
              <p className="text-sm text-text-primary whitespace-pre-wrap">
                {engagement.notes || 'No notes yet.'}
              </p>
            </div>

            {/* Edit button */}
            <button
              onClick={() => setIsEditing(true)}
              className="w-full px-4 py-2 bg-bg-tertiary text-text-primary rounded-md text-sm font-medium hover:bg-bg-primary transition-colors"
            >
              Edit
            </button>
          </>
        )}

        {/* Timestamps */}
        <div className="pt-4 border-t border-border space-y-1">
          <div className="text-xs text-text-tertiary">
            Created: {new Date(engagement.created_at).toLocaleDateString()}
          </div>
          <div className="text-xs text-text-tertiary">
            Updated: {new Date(engagement.updated_at).toLocaleDateString()}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-border">
        <button
          onClick={handleDelete}
          disabled={deleteMutation.isPending}
          className="w-full px-4 py-2 text-sm text-red-400 hover:bg-red-500/10 rounded-md transition-colors"
        >
          {deleteMutation.isPending ? 'Removing...' : 'Remove from Pipeline'}
        </button>
      </div>
    </div>
  )
}
```

**Step 2: Add useEffect import**

Make sure `useEffect` is imported at the top:

```typescript
import { useState, useMemo, useEffect } from 'react'
```

**Step 3: Add useUpdateEngagement import**

Make sure `useUpdateEngagement` is imported:

```typescript
import {
  useEngagementBoard,
  useUpdateEngagementStage,
  useUpdateEngagement,  // Add this
  useCreateEngagement,
  useDeleteEngagement,
  useEntityAutocomplete,
  type Engagement,
  type EntityAutocompleteResult,
} from '../hooks/useApi'
```

**Step 4: Verify edit works**

Run: `cd frontend && npm run dev`

Test: Click a card, click Edit, change fields, click Save

Expected: Changes persist, detail panel updates

**Step 5: Commit**

```bash
git add frontend/src/views/EngagementPipeline.tsx
git commit -m "feat(frontend): add edit functionality to engagement detail panel

- Edit mode toggle for stage, priority, notes
- Save/cancel buttons
- Reset state when engagement changes"
```

---

## Task 10: Final Testing and Polish

**Step 1: Run full test cycle**

```bash
# Build backend to verify no syntax errors
cd backend && python -c "from api.main import app; print('Backend OK')"

# Build frontend to verify types
cd frontend && npm run build

# Start both and test manually
cd .. && start.bat
```

**Step 2: Test all functionality**

1. Navigate to Pipeline
2. Click "Add Entity" - search and add an entity
3. Verify card appears in "Targeted" column
4. Drag card to another column - verify stage updates
5. Click card - verify detail panel opens
6. Click Edit - change priority and notes
7. Save - verify changes persist
8. Remove - verify card is deleted

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete Engagement Pipeline feature

Kanban board for tracking top-of-funnel DoD engagement:
- SQLite table for engagement data (separate from vault)
- Full CRUD API endpoints
- Drag-and-drop stage management
- Entity search/autocomplete for quick-add
- Filters by entity type, priority
- Detail panel with edit/delete
- Pipeline navigation in sidebar"
```

---

## Summary

This plan creates a complete Engagement Pipeline feature with:

| Component | Description |
|-----------|-------------|
| Database | `engagements` table in SQLite |
| API | 7 endpoints for CRUD + stats + autocomplete |
| Frontend | Kanban view with drag-drop, filters, quick-add |
| Navigation | Sidebar link + route |

**Files touched:**
- `backend/api/main.py` - Database schema + API endpoints
- `frontend/src/hooks/useApi.ts` - API hooks
- `frontend/src/views/EngagementPipeline.tsx` - Main view
- `frontend/src/App.tsx` - Route
- `frontend/src/components/Layout.tsx` - Navigation
- `frontend/package.json` - dnd-kit dependency
