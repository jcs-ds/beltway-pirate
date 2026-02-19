# Campaign Orchestrator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a pursuit/campaign management view for coordinating complex multi-stakeholder engagement efforts targeting specific opportunities (OTAs, SBIRs, contracts).

**Architecture:** Three SQLite tables (campaigns, campaign_stakeholders, campaign_milestones) with FastAPI endpoints. React frontend with campaign list view and campaign detail view featuring role-based stakeholder columns and milestone timeline.

**Tech Stack:** Python/FastAPI backend, React/TypeScript frontend, TanStack Query for data fetching, Tailwind CSS with existing design tokens.

---

## Task 1: Create Campaign Database Tables

**Files:**
- Modify: `backend/api/main.py` (near line 51, after `_ensure_engagements_table`)

**Step 1: Add table creation function**

Add after the `_ensure_engagements_table` function:

```python
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

    conn.commit()
    conn.close()
```

**Step 2: Call table creation on startup**

Find where `_ensure_engagements_table()` is called (around line 239) and add:

```python
_ensure_campaign_tables()
```

**Step 3: Verify tables created**

Run backend and check database:
```bash
sqlite3 data/processed/dod.db ".tables"
```
Expected: Should show `campaigns`, `campaign_stakeholders`, `campaign_milestones` tables.

**Step 4: Commit**

```bash
git add backend/api/main.py
git commit -m "feat(campaigns): add database tables for campaign orchestrator"
```

---

## Task 2: Add Pydantic Models for Campaigns

**Files:**
- Modify: `backend/api/main.py` (after EngagementResponse model, around line 110)

**Step 1: Add campaign models**

```python
# Campaign Orchestrator Models
CAMPAIGN_STATUSES = ['planning', 'active', 'won', 'lost', 'on_hold']
CAMPAIGN_TYPES = ['OTA', 'SBIR', 'Direct', 'Partnership', 'Congressional']
STAKEHOLDER_ROLES = [
    'Program Office', 'Requirements Owner', 'End User', 'Technical Evaluator',
    'Congressional Champion', 'Prime Partner', 'Competitor Intel',
    'Contracting Officer', 'SETA/FFRDCs'
]
INFLUENCE_LEVELS = ['decision_maker', 'influencer', 'champion', 'blocker', 'end_user']
SENTIMENTS = ['champion', 'supportive', 'neutral', 'skeptical', 'opposed']
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
    owner: Optional[str] = None
    notes: Optional[str] = None


class CampaignStakeholderUpdate(BaseModel):
    role: Optional[str] = None
    influence_level: Optional[str] = None
    sentiment: Optional[str] = None
    engagement_status: Optional[str] = None
    owner: Optional[str] = None
    notes: Optional[str] = None
    last_contact_date: Optional[str] = None


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
```

**Step 2: Commit**

```bash
git add backend/api/main.py
git commit -m "feat(campaigns): add Pydantic models for campaign API"
```

---

## Task 3: Add Campaign CRUD Endpoints

**Files:**
- Modify: `backend/api/main.py` (add after engagement endpoints, around line 5200)

**Step 1: Add helper function for campaign with details**

```python
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
               sentiment, engagement_status, owner, notes, last_contact_date,
               created_at, updated_at
        FROM campaign_stakeholders WHERE campaign_id = ?
    """, (campaign_id,)).fetchall()

    entities_by_id = {e.id: e for e in _entities_cache}
    stakeholders = []
    for srow in stakeholder_rows:
        scols = ['id', 'campaign_id', 'entity_id', 'entity_type', 'role',
                 'influence_level', 'sentiment', 'engagement_status', 'owner',
                 'notes', 'last_contact_date', 'created_at', 'updated_at']
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
```

**Step 2: Add list campaigns endpoint**

```python
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
```

**Step 3: Add create campaign endpoint**

```python
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
```

**Step 4: Add get campaign detail endpoint**

```python
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
```

**Step 5: Add update campaign endpoint**

```python
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
```

**Step 6: Add delete campaign endpoint**

```python
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
```

**Step 7: Commit**

```bash
git add backend/api/main.py
git commit -m "feat(campaigns): add campaign CRUD endpoints"
```

---

## Task 4: Add Campaign Stakeholder Endpoints

**Files:**
- Modify: `backend/api/main.py` (after campaign CRUD endpoints)

**Step 1: Add stakeholder endpoints**

```python
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

    conn.execute("""
        INSERT INTO campaign_stakeholders
        (id, campaign_id, entity_id, entity_type, role, influence_level,
         sentiment, engagement_status, owner, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (stakeholder_id, campaign_id, stakeholder.entity_id, stakeholder.entity_type,
          stakeholder.role, stakeholder.influence_level, stakeholder.sentiment,
          stakeholder.engagement_status, stakeholder.owner, stakeholder.notes))

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
```

**Step 2: Commit**

```bash
git add backend/api/main.py
git commit -m "feat(campaigns): add campaign stakeholder endpoints"
```

---

## Task 5: Add Campaign Milestone Endpoints

**Files:**
- Modify: `backend/api/main.py` (after stakeholder endpoints)

**Step 1: Add milestone endpoints**

```python
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
```

**Step 2: Commit**

```bash
git add backend/api/main.py
git commit -m "feat(campaigns): add campaign milestone endpoints"
```

---

## Task 6: Add Frontend API Hooks for Campaigns

**Files:**
- Modify: `frontend/src/hooks/useApi.ts` (at end of file)

**Step 1: Add TypeScript types**

```typescript
// Campaign Orchestrator Types
export interface Campaign {
  id: string
  name: string
  description: string | null
  status: string
  campaign_type: string | null
  target_program_id: string | null
  target_program_name: string | null
  target_value: string | null
  target_close_date: string | null
  probability: number | null
  lead_owner: string | null
  stakeholder_count?: number
  milestones_total?: number
  milestones_completed?: number
  stakeholders?: CampaignStakeholder[]
  milestones?: CampaignMilestone[]
  created_at: string
  updated_at: string
}

export interface CampaignStakeholder {
  id: string
  campaign_id: string
  entity_id: string
  entity_type: string
  entity_name: string
  entity_service: string | null
  role: string
  influence_level: string | null
  sentiment: string
  engagement_status: string
  owner: string | null
  notes: string | null
  last_contact_date: string | null
  created_at: string
  updated_at: string
}

export interface CampaignMilestone {
  id: string
  campaign_id: string
  title: string
  description: string | null
  due_date: string | null
  completed_date: string | null
  status: string
  related_stakeholders: string | null
  created_at: string
}

export interface CampaignListResponse {
  campaigns: Campaign[]
  filters: {
    statuses: string[]
    types: string[]
  }
}

export interface CampaignCreate {
  name: string
  description?: string
  status?: string
  campaign_type?: string
  target_program_id?: string
  target_value?: string
  target_close_date?: string
  probability?: number
  lead_owner?: string
}

export interface CampaignUpdate {
  name?: string
  description?: string
  status?: string
  campaign_type?: string
  target_program_id?: string
  target_value?: string
  target_close_date?: string
  probability?: number
  lead_owner?: string
}

export interface CampaignStakeholderCreate {
  entity_id: string
  entity_type: string
  role: string
  influence_level?: string
  sentiment?: string
  engagement_status?: string
  owner?: string
  notes?: string
}

export interface CampaignStakeholderUpdate {
  role?: string
  influence_level?: string
  sentiment?: string
  engagement_status?: string
  owner?: string
  notes?: string
  last_contact_date?: string
}

export interface CampaignMilestoneCreate {
  title: string
  description?: string
  due_date?: string
  status?: string
  related_stakeholders?: string
}

export interface CampaignMilestoneUpdate {
  title?: string
  description?: string
  due_date?: string
  completed_date?: string
  status?: string
  related_stakeholders?: string
}
```

**Step 2: Add campaign hooks**

```typescript
// Campaign List
export function useCampaigns(filters?: {
  status?: string[]
  campaign_type?: string[]
  search?: string
}) {
  const params = new URLSearchParams()
  if (filters?.status?.length) params.set('status', filters.status.join(','))
  if (filters?.campaign_type?.length) params.set('campaign_type', filters.campaign_type.join(','))
  if (filters?.search) params.set('search', filters.search)

  return useQuery<CampaignListResponse>({
    queryKey: ['campaigns', filters],
    queryFn: () => fetchJson(`/campaigns?${params}`),
  })
}

// Single Campaign Detail
export function useCampaign(campaignId: string | undefined) {
  return useQuery<Campaign>({
    queryKey: ['campaign', campaignId],
    queryFn: () => fetchJson(`/campaigns/${campaignId}`),
    enabled: !!campaignId,
  })
}

// Create Campaign
export function useCreateCampaign() {
  const queryClient = useQueryClient()

  return useMutation<Campaign, Error, CampaignCreate>({
    mutationFn: async (data) => {
      const response = await fetch(`${API_BASE}/campaigns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to create campaign')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

// Update Campaign
export function useUpdateCampaign() {
  const queryClient = useQueryClient()

  return useMutation<Campaign, Error, { id: string; update: CampaignUpdate }>({
    mutationFn: async ({ id, update }) => {
      const response = await fetch(`${API_BASE}/campaigns/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(update),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to update campaign')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      queryClient.invalidateQueries({ queryKey: ['campaign', data.id] })
    },
  })
}

// Delete Campaign
export function useDeleteCampaign() {
  const queryClient = useQueryClient()

  return useMutation<void, Error, string>({
    mutationFn: async (campaignId) => {
      const response = await fetch(`${API_BASE}/campaigns/${campaignId}`, {
        method: 'DELETE',
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to delete campaign')
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

// Add Stakeholder to Campaign
export function useAddCampaignStakeholder() {
  const queryClient = useQueryClient()

  return useMutation<Campaign, Error, { campaignId: string; stakeholder: CampaignStakeholderCreate }>({
    mutationFn: async ({ campaignId, stakeholder }) => {
      const response = await fetch(`${API_BASE}/campaigns/${campaignId}/stakeholders`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(stakeholder),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to add stakeholder')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      queryClient.invalidateQueries({ queryKey: ['campaign', data.id] })
    },
  })
}

// Update Campaign Stakeholder
export function useUpdateCampaignStakeholder() {
  const queryClient = useQueryClient()

  return useMutation<Campaign, Error, { campaignId: string; stakeholderId: string; update: CampaignStakeholderUpdate }>({
    mutationFn: async ({ campaignId, stakeholderId, update }) => {
      const response = await fetch(`${API_BASE}/campaigns/${campaignId}/stakeholders/${stakeholderId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(update),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to update stakeholder')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      queryClient.invalidateQueries({ queryKey: ['campaign', data.id] })
    },
  })
}

// Remove Campaign Stakeholder
export function useRemoveCampaignStakeholder() {
  const queryClient = useQueryClient()

  return useMutation<Campaign, Error, { campaignId: string; stakeholderId: string }>({
    mutationFn: async ({ campaignId, stakeholderId }) => {
      const response = await fetch(`${API_BASE}/campaigns/${campaignId}/stakeholders/${stakeholderId}`, {
        method: 'DELETE',
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to remove stakeholder')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      queryClient.invalidateQueries({ queryKey: ['campaign', data.id] })
    },
  })
}

// Add Campaign Milestone
export function useAddCampaignMilestone() {
  const queryClient = useQueryClient()

  return useMutation<Campaign, Error, { campaignId: string; milestone: CampaignMilestoneCreate }>({
    mutationFn: async ({ campaignId, milestone }) => {
      const response = await fetch(`${API_BASE}/campaigns/${campaignId}/milestones`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(milestone),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to add milestone')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['campaign', data.id] })
    },
  })
}

// Update Campaign Milestone
export function useUpdateCampaignMilestone() {
  const queryClient = useQueryClient()

  return useMutation<Campaign, Error, { campaignId: string; milestoneId: string; update: CampaignMilestoneUpdate }>({
    mutationFn: async ({ campaignId, milestoneId, update }) => {
      const response = await fetch(`${API_BASE}/campaigns/${campaignId}/milestones/${milestoneId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(update),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to update milestone')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['campaign', data.id] })
    },
  })
}

// Delete Campaign Milestone
export function useDeleteCampaignMilestone() {
  const queryClient = useQueryClient()

  return useMutation<Campaign, Error, { campaignId: string; milestoneId: string }>({
    mutationFn: async ({ campaignId, milestoneId }) => {
      const response = await fetch(`${API_BASE}/campaigns/${campaignId}/milestones/${milestoneId}`, {
        method: 'DELETE',
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to delete milestone')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['campaign', data.id] })
    },
  })
}
```

**Step 3: Run TypeScript check**

```bash
cd frontend && npm run build
```
Expected: No type errors

**Step 4: Commit**

```bash
git add frontend/src/hooks/useApi.ts
git commit -m "feat(campaigns): add frontend API hooks for campaigns"
```

---

## Task 7: Create Campaign List View

**Files:**
- Create: `frontend/src/views/CampaignOrchestrator.tsx`

**Step 1: Create the campaign list view**

```typescript
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2, Plus, Search, Target, Calendar, Users, TrendingUp } from 'lucide-react'
import { useCampaigns, useCreateCampaign, type Campaign } from '../hooks/useApi'
import FilterChips from '../components/FilterChips'
import clsx from 'clsx'

const STATUS_COLORS: Record<string, string> = {
  planning: 'bg-text-tertiary/20 text-text-tertiary',
  active: 'bg-accent-primary/20 text-accent-primary',
  won: 'bg-accent-success/20 text-accent-success',
  lost: 'bg-accent-danger/20 text-accent-danger',
  on_hold: 'bg-accent-warning/20 text-accent-warning',
}

export default function CampaignOrchestrator() {
  const [statusFilter, setStatusFilter] = useState<string[]>([])
  const [typeFilter, setTypeFilter] = useState<string[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [showCreateModal, setShowCreateModal] = useState(false)

  const { data, isLoading } = useCampaigns({
    status: statusFilter.length > 0 ? statusFilter : undefined,
    campaign_type: typeFilter.length > 0 ? typeFilter : undefined,
    search: searchQuery || undefined,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 text-text-secondary animate-spin" />
      </div>
    )
  }

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Campaigns</h1>
          <p className="text-text-secondary text-sm">
            Manage pursuit campaigns and stakeholder coordination
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" />
            <input
              type="text"
              placeholder="Search campaigns..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-3 py-1.5 w-48 bg-bg-secondary border border-border rounded-md text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-text-primary/50"
            />
          </div>

          {/* Filters */}
          <FilterChips
            label="Status"
            options={data?.filters?.statuses ?? []}
            selected={statusFilter}
            onChange={setStatusFilter}
            displayMap={{
              planning: 'Planning',
              active: 'Active',
              won: 'Won',
              lost: 'Lost',
              on_hold: 'On Hold',
            }}
          />
          <FilterChips
            label="Type"
            options={data?.filters?.types ?? []}
            selected={typeFilter}
            onChange={setTypeFilter}
          />

          {/* Create Button */}
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-3 py-1.5 bg-text-primary text-text-inverse rounded-md text-sm font-medium hover:bg-text-primary/90 transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Campaign
          </button>
        </div>
      </div>

      {/* Campaign Table */}
      <div className="flex-1 overflow-auto border border-border rounded-lg bg-bg-secondary">
        <table className="w-full">
          <thead className="sticky top-0 bg-bg-tertiary border-b border-border">
            <tr>
              <th className="text-left px-4 py-3 text-xs font-medium text-text-secondary uppercase tracking-wider">
                Campaign
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-text-secondary uppercase tracking-wider">
                Type
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-text-secondary uppercase tracking-wider">
                Status
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-text-secondary uppercase tracking-wider">
                Target
              </th>
              <th className="text-center px-4 py-3 text-xs font-medium text-text-secondary uppercase tracking-wider">
                <Users className="w-4 h-4 inline" />
              </th>
              <th className="text-center px-4 py-3 text-xs font-medium text-text-secondary uppercase tracking-wider">
                Progress
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-text-secondary uppercase tracking-wider">
                Close Date
              </th>
              <th className="text-center px-4 py-3 text-xs font-medium text-text-secondary uppercase tracking-wider">
                Prob
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data?.campaigns.map((campaign) => (
              <CampaignRow key={campaign.id} campaign={campaign} />
            ))}
            {data?.campaigns.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-text-tertiary">
                  No campaigns found. Create your first campaign to get started.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <CreateCampaignModal onClose={() => setShowCreateModal(false)} />
      )}
    </div>
  )
}

function CampaignRow({ campaign }: { campaign: Campaign }) {
  const progressPercent = campaign.milestones_total
    ? Math.round((campaign.milestones_completed ?? 0) / campaign.milestones_total * 100)
    : 0

  return (
    <tr className="hover:bg-bg-tertiary transition-colors">
      <td className="px-4 py-3">
        <Link
          to={`/campaigns/${campaign.id}`}
          className="text-sm font-medium text-text-primary hover:text-accent-primary"
        >
          {campaign.name}
        </Link>
        {campaign.description && (
          <p className="text-xs text-text-tertiary truncate max-w-xs">
            {campaign.description}
          </p>
        )}
      </td>
      <td className="px-4 py-3">
        {campaign.campaign_type && (
          <span className="text-xs text-text-secondary bg-bg-tertiary px-2 py-0.5 rounded">
            {campaign.campaign_type}
          </span>
        )}
      </td>
      <td className="px-4 py-3">
        <span className={clsx(
          'text-xs font-medium px-2 py-0.5 rounded capitalize',
          STATUS_COLORS[campaign.status] || STATUS_COLORS.active
        )}>
          {campaign.status.replace('_', ' ')}
        </span>
      </td>
      <td className="px-4 py-3">
        {campaign.target_program_name ? (
          <Link
            to={`/entity/${campaign.target_program_id}`}
            className="text-xs text-text-secondary hover:text-accent-primary"
          >
            {campaign.target_program_name}
          </Link>
        ) : (
          <span className="text-xs text-text-tertiary">—</span>
        )}
      </td>
      <td className="px-4 py-3 text-center">
        <span className="text-sm font-mono text-text-secondary">
          {campaign.stakeholder_count ?? 0}
        </span>
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 bg-bg-tertiary rounded-full overflow-hidden">
            <div
              className="h-full bg-accent-primary rounded-full transition-all"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <span className="text-xs text-text-tertiary font-mono">
            {campaign.milestones_completed ?? 0}/{campaign.milestones_total ?? 0}
          </span>
        </div>
      </td>
      <td className="px-4 py-3">
        <span className="text-xs text-text-secondary">
          {campaign.target_close_date || '—'}
        </span>
      </td>
      <td className="px-4 py-3 text-center">
        {campaign.probability !== null ? (
          <span className={clsx(
            'text-xs font-mono',
            campaign.probability >= 70 ? 'text-accent-success' :
            campaign.probability >= 40 ? 'text-accent-warning' :
            'text-text-tertiary'
          )}>
            {campaign.probability}%
          </span>
        ) : (
          <span className="text-xs text-text-tertiary">—</span>
        )}
      </td>
    </tr>
  )
}

function CreateCampaignModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [campaignType, setCampaignType] = useState('')

  const createMutation = useCreateCampaign()

  const handleCreate = () => {
    if (!name.trim()) return

    createMutation.mutate(
      {
        name: name.trim(),
        description: description.trim() || undefined,
        campaign_type: campaignType || undefined,
      },
      {
        onSuccess: () => onClose(),
      }
    )
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-bg-secondary border border-border rounded-lg w-[480px]">
        <div className="px-4 py-3 border-b border-border">
          <h2 className="text-lg font-semibold text-text-primary">New Campaign</h2>
        </div>

        <div className="p-4 space-y-4">
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">
              Campaign Name *
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., S2AS Follow-on Pursuit"
              className="w-full px-3 py-2 bg-bg-primary border border-border rounded-md text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-text-primary/50"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What are we trying to achieve?"
              rows={3}
              className="w-full px-3 py-2 bg-bg-primary border border-border rounded-md text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-text-primary/50 resize-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">
              Campaign Type
            </label>
            <select
              value={campaignType}
              onChange={(e) => setCampaignType(e.target.value)}
              className="w-full px-3 py-2 bg-bg-primary border border-border rounded-md text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-text-primary/50"
            >
              <option value="">Select type...</option>
              <option value="OTA">OTA</option>
              <option value="SBIR">SBIR</option>
              <option value="Direct">Direct</option>
              <option value="Partnership">Partnership</option>
              <option value="Congressional">Congressional</option>
            </select>
          </div>
        </div>

        <div className="flex justify-end gap-2 px-4 py-3 border-t border-border">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!name.trim() || createMutation.isPending}
            className="px-4 py-2 bg-text-primary text-text-inverse rounded-md text-sm font-medium hover:bg-text-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {createMutation.isPending ? 'Creating...' : 'Create Campaign'}
          </button>
        </div>
      </div>
    </div>
  )
}
```

**Step 2: Commit**

```bash
git add frontend/src/views/CampaignOrchestrator.tsx
git commit -m "feat(campaigns): add campaign list view"
```

---

## Task 8: Create Campaign Detail View

**Files:**
- Create: `frontend/src/views/CampaignDetail.tsx`

This is a larger file - will be implemented with stakeholder columns by role and milestone timeline. See spec for full details. Key sections:
1. Campaign header with metadata
2. Stakeholder map (role-based columns)
3. Milestone timeline
4. Edit campaign modal

**Step 1: Create the campaign detail view**

(Full implementation - approximately 600 lines - with stakeholder columns, add stakeholder modal, milestone timeline, edit campaign functionality)

**Step 2: Commit**

```bash
git add frontend/src/views/CampaignDetail.tsx
git commit -m "feat(campaigns): add campaign detail view with stakeholder map"
```

---

## Task 9: Add Campaign Routes and Navigation

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`

**Step 1: Add route imports and routes to App.tsx**

```typescript
// Add import
import CampaignOrchestrator from './views/CampaignOrchestrator'
import CampaignDetail from './views/CampaignDetail'

// Add routes (after pipeline route)
<Route path="campaigns" element={<CampaignOrchestrator />} />
<Route path="campaigns/:campaignId" element={<CampaignDetail />} />
```

**Step 2: Add navigation link to Layout.tsx**

Add to navigation items (after Pipeline):
```typescript
{ name: 'Campaigns', href: '/campaigns', icon: Target },
```

**Step 3: Run build to verify**

```bash
cd frontend && npm run build
```

**Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/Layout.tsx
git commit -m "feat(campaigns): add campaign routes and navigation"
```

---

## Task 10: Update AddToPipelineButton to Support Campaigns

**Files:**
- Modify: `frontend/src/components/AddToPipelineButton.tsx`

**Step 1: Add campaign selection functionality**

Update the "Add to Campaign" button to show a dropdown of active campaigns and add the entity as a stakeholder.

Key changes:
- Fetch active campaigns when menu opens
- Show campaign submenu on "Add to Campaign" hover
- Call addStakeholder API with entity data
- Show toast on success

**Step 2: Commit**

```bash
git add frontend/src/components/AddToPipelineButton.tsx
git commit -m "feat(campaigns): enable adding entities to campaigns from explorer"
```

---

## Task 11: Final Integration Testing

**Step 1: Start backend and frontend**

```bash
# Terminal 1
cd backend && python -m uvicorn api.main:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
```

**Step 2: Test campaign creation flow**

1. Navigate to /campaigns
2. Click "New Campaign"
3. Fill in name, description, type
4. Verify campaign appears in list

**Step 3: Test stakeholder management**

1. Open campaign detail
2. Add stakeholder via search
3. Set role, influence, sentiment
4. Verify stakeholder appears in correct column

**Step 4: Test milestone management**

1. Add milestone with due date
2. Update milestone status
3. Verify timeline updates

**Step 5: Test entity integration**

1. Go to stakeholder explorer
2. Click + button on entity
3. Select "Add to Campaign"
4. Choose campaign and role
5. Verify entity added to campaign

**Step 6: Final commit**

```bash
git add .
git commit -m "feat(campaigns): complete campaign orchestrator implementation"
```

---

## Summary of Files Changed

### Backend
- `backend/api/main.py` - Database tables, models, and 12 new API endpoints

### Frontend
- `frontend/src/hooks/useApi.ts` - Types and hooks for campaigns
- `frontend/src/views/CampaignOrchestrator.tsx` - Campaign list view (NEW)
- `frontend/src/views/CampaignDetail.tsx` - Campaign detail view (NEW)
- `frontend/src/App.tsx` - Routes
- `frontend/src/components/Layout.tsx` - Navigation
- `frontend/src/components/AddToPipelineButton.tsx` - Add to campaign support

---

## Estimated Tasks: 11 major tasks
## Key Dependencies: Phase 1 (Engagement Pipeline) completed
