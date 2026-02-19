# Daily Digest Feature Design

**Date:** 2026-02-02
**Status:** Approved

## Overview

One-click generation of a curated "Top 5" digest from yesterday's articles (or Fri-Sun if Monday), plus any roundup/compilation content.

**Entry point:** "Daily Digest" button in NewsReader header, opens a modal.

**Core components:**
- Relevance Scorer - Keyword-based scoring weighted toward BD focus areas
- Roundup Detector - Identifies newsletters/compilations
- Digest Modal - Displays Top 5 + Roundups with links/descriptions
- PDF Generator - Minimal/clean export

## Data Flow

```
User clicks "Daily Digest"
    → Filter articles to relevant time window (yesterday, or Fri-Sun if Monday)
    → Exclude Tier 2b feeds entirely
    → Score each non-roundup article with relevance scorer
    → Take top 5 by score
    → Separately identify roundups
    → Render in modal
    → PDF export on demand
```

## Relevance Scoring System

Time window is a hard filter - yesterday only (or Fri-Sun if Monday). Tier 2b feeds excluded entirely.

### Score Calculation

```
Score = (keyword_score × 10) + tier_bonus
```

### Keyword Weights (cumulative)

| Category | Keywords | Points |
|----------|----------|--------|
| EW/Spectrum | electronic warfare, ew, spectrum, jamming, sigint, elint, emso | 15 |
| Counter-UAS | counter-uas, c-uas, counter-drone, anti-drone | 15 |
| Sensing | radar, sensor, isr, c4isr, surveillance, reconnaissance, targeting, detection | 12 |
| Autonomy | autonomous, unmanned, drone, uav, uas, robotics, uncrewed | 12 |
| AI/ML | artificial intelligence, machine learning, ai-enabled, neural network, computer vision, algorithm | 12 |
| Acquisition | acquisition, procurement, contract, rfp, rfi, award, program office, peo | 10 |
| Core Defense | pentagon, dod, defense, military, warfare | 5 |

### Tier Bonus

- Tier 1: +20 points
- Tier 2a: +15 points

### Tiebreaker

Tier 1 → Tier 2a, then most recent.

## Roundup Detection

An article is flagged as a "roundup" if either condition is true:

### Condition 1: Title Keywords (case-insensitive)

- newsletter, roundup, round-up, digest, briefing
- weekly, daily, quarterly, monthly
- this week in, week in review
- what we're reading, morning, evening

### Condition 2: Kill the Newsletter Source

Any article from a feed URL containing `kill-the-newsletter.com` is automatically a roundup.

### Behavior

- Roundups excluded from Top 5 scoring
- Displayed in separate "Roundups" section below Top 5
- Sorted by date (newest first)

## Modal UI

**Trigger:** "Daily Digest" button in NewsReader header

**Layout:** Centered modal, ~600px wide, max-height 80vh with scroll

```
┌─────────────────────────────────────────────────────┐
│  Daily Digest                              [X] Close │
│  Friday, January 31, 2026                           │
│  (or: "Weekend Edition - Fri-Sun" if Monday)        │
├─────────────────────────────────────────────────────┤
│                                                     │
│  TOP 5                                              │
│  ─────                                              │
│  1. Article Title Here                              │
│     Source Name • 2-3 sentence description...       │
│     [Read →]                                        │
│                                                     │
│  2. Another Article Title                           │
│     Source Name • Brief description...              │
│     [Read →]                                        │
│                                                     │
│  ... (3, 4, 5)                                      │
│                                                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ROUNDUPS & COMPILATIONS (4)                        │
│  ───────────────────────────                        │
│  • WOTR Newsletter - War on the Rocks    [Read →]   │
│  • CSIS DSD Brief - CSIS                 [Read →]   │
│  ...                                                │
│                                                     │
├─────────────────────────────────────────────────────┤
│                              [Download PDF]         │
└─────────────────────────────────────────────────────┘
```

**Interactions:**
- [Read →] opens article link in new tab
- [X] or click outside closes modal
- [Download PDF] generates and downloads PDF

**Empty states:**
- No Top 5: "No high-relevance articles from yesterday"
- No roundups: Section hidden

## PDF Export

**Filename:** `beltway-pirate-digest-YYYY-MM-DD.pdf`

**Format:** Minimal, clean, prints well

```
────────────────────────────────────────────────────────

DAILY DIGEST
January 31, 2026

────────────────────────────────────────────────────────

TOP 5

1. Article Title Here
   Source Name
   Description text...
   → https://example.com/article-link

2. ...

────────────────────────────────────────────────────────

ROUNDUPS & COMPILATIONS

• WOTR Newsletter - War on the Rocks
  → https://warontherocks.com/...

────────────────────────────────────────────────────────

Generated by Beltway Pirate

────────────────────────────────────────────────────────
```

**Technical approach:** Use `html2pdf.js` for client-side generation.

## Implementation Tasks

1. Add `html2pdf.js` dependency
2. Create `digestUtils.ts` with scoring and roundup detection functions
3. Create `DigestModal.tsx` component
4. Add "Daily Digest" button to NewsReader header
5. Implement PDF export functionality
6. Test with real feed data
