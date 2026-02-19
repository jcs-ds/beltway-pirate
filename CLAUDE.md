# CLAUDE.md - AI Agent Context for Beltway Pirate

This file provides essential context for AI agents working on this codebase. Read this FIRST before starting any task.

## Project Overview

**Beltway Pirate** - a local web app for browsing a DoD knowledge base. The knowledge base lives in an Obsidian vault; this app provides specialized explorers, search, and visualization on top of that data.

**Key insight**: This is a READ layer on top of an Obsidian vault. The vault is the source of truth. The app ingests vault markdown files into SQLite for fast querying, but edits should flow back to the vault.

## The Vault-to-App Data Flow

```
Obsidian Vault (Markdown + YAML frontmatter)
    │
    ▼ [POST /api/rebuild]
SQLite Database (dod.db) with FTS5 search
    │
    ▼ [GET /api/* endpoints]
React Frontend (explorers, search, graphs)
```

### Vault Location
```
C:/Users/jcsul/OneDrive/Documents/jcs-remote/Distributed
```

### Vault Structure
```
Distributed/
├── Competitors/          # Competitor company profiles
├── Organizations/        # DoD orgs, Congress, Executive Branch
│   ├── Air-Force/       # Service-specific stakeholders, programs, units
│   ├── Army/
│   ├── Navy/
│   ├── USMC/
│   ├── Space-Force/
│   ├── Coast-Guard/
│   ├── SOCOM/
│   ├── Congress/        # Committees and members
│   ├── Executive-Branch/
│   ├── DoD/             # OSD, Joint Staff
│   ├── [COCOMs]/        # INDOPACOM, EUCOM, CENTCOM, etc.
│   └── ...
├── Platforms/           # Blue Force and Red Force platforms
│   ├── Air/
│   ├── Ground/
│   ├── Sea/
│   ├── Space/
│   └── Red/             # Adversary platforms (China, Russia, Iran, etc.)
├── Technology/          # Modalities and techniques
└── Reference/
    ├── Templates/       # Entity templates (critical for understanding schema)
    ├── MOCs/           # Maps of Content (filtered out of app)
    └── assets/         # Images, icons
```

### Frontmatter Schema (by entity type)
Each markdown file has YAML frontmatter. Key fields vary by type:

**Programs** (`tags: [program]`):
- `service`, `domain`, `acquisition_phase`, `program_office`, `platform`

**Platforms** (`tags: [platform]`):
- `service`, `domain`, `manufacturer`, `force` (blue/red), `country` (for red)

**Stakeholders** (`tags: [buyer, stakeholder]`):
- `organization_type` (PEO, Lab, Enabler, Requirements), `parent_org`, `service`

**Units** (`tags: [unit]`):
- `service`, `cocom`, `unit_type`, `parent_unit`

**Congress Members** (`tags: [congress_member]`):
- `party`, `state`, `chamber`, `committees`

**Competitors** (`tags: [competitor]`):
- `category` (Prime, Startup, SME), `ds_relationship`, `domain`

**Technology** (`tags: [technology]`):
- `modality_type` (Sensing, Autonomy, Counter), `related_programs`

### WikiLinks
The vault uses Obsidian WikiLinks for relationships:
- `[[Entity-Name]]` - link to another entity
- `[[Entity-Name|Display Text]]` - link with custom display text

These become the relationship graph in the app.

## Architecture

### Backend (Python/FastAPI)
- **Main API**: `backend/api/main.py` (~4000 lines, single file)
- **Database**: SQLite + FTS5 at `data/processed/dod.db`
- **Ingest**: `backend/ingest/markdown_parser.py`

### Frontend (React/TypeScript)
- **Views**: `frontend/src/views/` - one file per explorer
- **Components**: `frontend/src/components/`
- **API Hooks**: `frontend/src/hooks/useApi.ts` (TanStack Query)
- **State**: `frontend/src/stores/` (Zustand stores)
- **Design Tokens**: `frontend/tailwind.config.js`

### Current Stats (January 2025)
- **1,768 total entities**
- 669 programs, 473 units, 193 platforms (118 blue + 75 red)
- 185 Congress members, 135 stakeholders, 51 competitors
- 7,479 WikiLink relationships

## Design System: "Operational Elegance"

Dark theme inspired by Bloomberg Terminal. Use semantic tokens:

```
Backgrounds: bg-bg-primary, bg-bg-secondary, bg-bg-tertiary
Text: text-text-primary, text-text-secondary, text-text-tertiary
Accents: text-accent-primary (blue), text-accent-warning (amber),
         text-accent-danger (red), text-accent-success (green)
```

- Typography: IBM Plex Sans (body), JetBrains Mono (data)
- High density layouts, 8px grid, max border-radius 8px
- Minimal shadows, prefer subtle borders

## Key Patterns

### Multi-Select Filters
All explorers use cumulative multi-select dropdown filters (FilterChips component):
- Click dropdown to open, checkboxes inside for multi-select
- Backend accepts comma-separated values: `?service=Army,Navy`
- Backend normalizes compound values (e.g., "Army, Navy" platform → matches both filters)

### Normalization Functions (in main.py)
- `_normalize_service()` - splits "Army, Marines, AF" → ["Army", "Marines", "Air Force"]
- `_normalize_country()` - splits "Russia (manufactured), China" → ["China", "Russia"]
- `_normalize_program_domain()` - maps 148 domains → 15 intuitive groups
- `_normalize_political_role()` - maps 74 roles → 12 committee groups

### API Endpoint Pattern
- `/api/{domain}/explorer` - list data with filters
- `/api/{domain}/{id}` - single entity detail

### Reference File Filtering
The API excludes these from explorers (check `is_reference_file()`):
- Files with "moc-" or "moc_" prefix
- Files with "summary" in filename
- Files with "landscape" in filename

## Explorer Features

| Explorer | Key Features |
|----------|--------------|
| Platforms | Blue/Red toggle, service filter (blue), country filter (red) |
| Programs | Domain filter (15 normalized groups) |
| Units | COCOM theater filter |
| Stakeholders | Category + Domain multi-select |
| Competitors | Relationship + Domain multi-select |
| Political Affairs | Party + Committee (12 groups) filters |
| Technology | Modality cards with market landscape |
| News | RSS aggregator with save/delete, tier filtering |

## Common Tasks

### Rebuild Database from Vault
```bash
curl -X POST http://localhost:8000/api/rebuild
```

### Add New Entity Type
1. Create template in vault: `Reference/Templates/Template-NewType.md`
2. Add backend endpoint in `main.py`
3. Add API hook in `useApi.ts`
4. Create view in `frontend/src/views/`
5. Add route in `App.tsx`, sidebar link in `Layout.tsx`

### Add Platform Images
Images go in `frontend/public/platform-icons/{name}.png`
Use `scripts/download_platform_icons.py` for Wikimedia sourcing

## Build Commands

```bash
# Backend (from project root)
cd backend && python -m uvicorn api.main:app --reload --port 8000

# Frontend (from project root)
cd frontend && npm run dev      # Development
cd frontend && npm run build    # Type check + production build

# Full stack (Windows)
start.bat
```

## File Quick Reference

| Purpose | File |
|---------|------|
| All API endpoints | `backend/api/main.py` |
| API hooks | `frontend/src/hooks/useApi.ts` |
| Filter normalization | `backend/api/main.py` (search for `_normalize_`) |
| Multi-select dropdown | `frontend/src/components/FilterChips.tsx` |
| Design tokens | `frontend/tailwind.config.js` |
| News feed state | `frontend/src/stores/newsStore.ts` |
| RSS feed config | `frontend/src/config/feeds.ts` |
| Vault templates | `{vault}/Reference/Templates/` |

## Debugging Tips

- **Stale backend**: Kill all Python processes, delete `__pycache__`, restart uvicorn
- **Missing entities**: Check if file has correct frontmatter tags
- **Filter not working**: Check normalization functions in main.py
- **Frontend type errors**: Run `npm run build` to see all errors

