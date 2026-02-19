# beltway-pirate

# Beltway Pirate

A local web application for exploring a DoD knowledge base. Built as a specialized browser on top of an md filebase, providing filtered explorers, search, and relationship visualization.

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                      md Vault                                   │
│  (Markdown files with YAML frontmatter + WikiLinks)             │
│                                                                 │
│  Distributed/                                                   │
│  ├── Organizations/  (stakeholders, programs, units by service) │
│  ├── Platforms/      (blue force + red force assets)            │
│  ├── Competitors/    (competitor company profiles)              │
│  ├── Technology/     (sensing modalities, techniques)           │
│  └── Reference/      (templates, MOCs, assets)                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ POST /api/rebuild
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SQLite Database                              │
│  (dod.db with FTS5 full-text search)                           │
│                                                                 │
│  1,768 entities │ 7,479 relationships │ Real-time queries      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ GET /api/* endpoints
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    React Frontend                               │
│                                                                 │
│  Explorers: Programs │ Platforms │ Units │ Stakeholders        │
│             Competitors │ Political Affairs │ Technology        │
│                                                                 │
│  Features: Multi-select filters │ Search │ Graph view │ News   │
└─────────────────────────────────────────────────────────────────┘
```

**The vault is the source of truth.** This app provides a fast, filterable read layer with specialized views for different entity types.

## Quick Start

### Windows
```cmd
start.bat
```

### Linux/Mac
```bash
./start.sh
```

Then open http://localhost:5173

## Vault Structure

The app reads from an Obsidian vault at:
```
C:\Users\jcsul\OneDrive\Documents\jcs-remote\Distributed
```

### Entity Types & Vault Locations

| Entity Type | Vault Path | Tags |
|-------------|------------|------|
| Programs | `Organizations/{Service}/Programs/` | `program` |
| Platforms (Blue) | `Platforms/{Domain}/` | `platform` + `force: blue` |
| Platforms (Red) | `Platforms/Red/` | `platform` + `force: red` |
| Units | `Organizations/{Service}/Units/` | `unit` |
| Stakeholders | `Organizations/{Service}/` | `buyer`, `stakeholder` |
| Competitors | `Competitors/` | `competitor` |
| Congress | `Organizations/Congress/` | `congress_member`, `congress_committee` |
| Executive | `Organizations/Executive-Branch/` | `executive_official`, `executive_office` |
| Technology | `Technology/` | `technology` |

### Frontmatter Examples

**Program:**
```yaml
---
tags: [program]
service: Navy
domain: EW / Cyber / SIGINT
acquisition_phase: Production
program_office: "[[PEO-IWS]]"
---
```

**Platform (Blue):**
```yaml
---
tags: [platform]
service: Air Force
domain: Air
force: blue
manufacturer: Lockheed Martin
---
```

**Platform (Red):**
```yaml
---
tags: [platform]
force: red
country: China
domain: Air
---
```

### Templates

Entity templates live in `Reference/Templates/` and define the frontmatter schema for each type:
- `Template-Program.md`
- `Template-Platform.md`, `Template-Red-Platform.md`
- `Template-Congress-Member.md`, `Template-Congress-Committee.md`
- `Template-Competitor.md`
- etc.

## Features

### Explorers

| Explorer | Description | Filters |
|----------|-------------|---------|
| **Programs** | 669 DoD acquisition programs | Domain (15 groups) |
| **Platforms** | 193 platforms (118 blue, 75 red) | Blue: Service (8) / Red: Country (7) |
| **Units** | 473 operational military units | COCOM Theater |
| **Stakeholders** | 135 DoD organizations | Category + Domain |
| **Competitors** | 51 competitor companies | Relationship + Domain |
| **Political Affairs** | Congress + Executive | Party + Committee (12 groups) |
| **Technology** | 24 sensing/autonomy modalities | Cards with market landscape |

### Other Features

- **Search**: Full-text search across all entities
- **Graph View**: Interactive relationship visualization
- **News Feed**: RSS aggregator for defense news (33 curated feeds)
- **Entity Detail**: Full metadata + relationship sidebar
- **Inline Editing**: Edit entities directly in the app

### Filter System

All explorers use **multi-select dropdown filters**:
- Click to open dropdown with checkboxes
- Select multiple values (e.g., Army + Navy)
- Backend normalizes compound values (a platform tagged "Army, Navy" matches both filters)

## Tech Stack

### Backend
- Python 3.11+ / FastAPI
- SQLite with FTS5 full-text search
- ~4000 lines in single `main.py`

### Frontend
- React 18 / TypeScript 5
- TanStack Query (data fetching)
- Zustand (state management)
- Tailwind CSS ("Operational Elegance" dark theme)

## Development

### Manual Setup

**Backend:**
```bash
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
cd backend && python -m uvicorn api.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

### Rebuild Database

After vault changes:
```bash
curl -X POST http://localhost:8000/api/rebuild
```

### Type Check
```bash
cd frontend && npm run build
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats` | Database statistics |
| `GET /api/search?q=` | Full-text search |
| `GET /api/programs/explorer` | Programs list with filters |
| `GET /api/platforms/browser?view=blue` | Platforms with service/country filter |
| `GET /api/units/explorer` | Units with COCOM filter |
| `GET /api/buyers/explorer` | Stakeholders with category/domain |
| `GET /api/competitors/explorer` | Competitors with relationship/domain |
| `GET /api/political-affairs/explorer` | Congress + Executive |
| `GET /api/modalities` | Technology modalities |
| `GET /api/entities/{id}` | Entity detail |
| `POST /api/rebuild` | Rebuild database from vault |

## Project Structure

```
beltway-pirate/
├── backend/
│   ├── api/main.py          # All API endpoints
│   ├── ingest/              # Vault parsing
│   └── db/                  # Database operations
├── frontend/
│   ├── src/
│   │   ├── views/           # Explorer pages
│   │   ├── components/      # Reusable UI (FilterChips, etc.)
│   │   ├── hooks/useApi.ts  # TanStack Query hooks
│   │   ├── stores/          # Zustand state
│   │   └── config/feeds.ts  # RSS feed configuration
│   └── tailwind.config.js   # Design tokens
├── data/processed/dod.db    # SQLite database
├── scripts/                 # Utility scripts
└── CLAUDE.md               # AI agent context
```

## Design System

"Operational Elegance" - Bloomberg Terminal-inspired dark theme:

- **Fonts**: IBM Plex Sans (body), JetBrains Mono (data)
- **Colors**: Dark backgrounds (#0D1117), blue accent (#58A6FF)
- **Density**: High information density, 8px grid
- **Style**: Subtle borders, minimal shadows, max 8px radius
