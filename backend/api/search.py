"""Search API with natural language query parsing."""
import re
from typing import Dict, List, Optional, Any
from backend.models.entities import Entity, SearchResult, EntityType


# Service detection patterns
SERVICE_PATTERNS = {
    "army": ["army", "usa"],
    "navy": ["navy", "usn", "naval"],
    "marines": ["marines", "usmc", "marine corps"],
    "air force": ["air force", "usaf", "af"],
    "space force": ["space force", "ussf", "space"],
    "socom": ["socom", "special operations", "sof", "jsoc"],
    "joint": ["joint", "dod", "osd"],
    "darpa": ["darpa"],
    "cybercom": ["cybercom", "cyber command"],
}

# Domain detection patterns
DOMAIN_PATTERNS = {
    "ew": ["ew", "electronic warfare", "spectrum", "jamming", "electronic attack"],
    "sigint": ["sigint", "signals intelligence", "comint", "elint"],
    "c-uas": ["c-uas", "counter-uas", "counter-drone", "cuas", "anti-drone"],
    "isr": ["isr", "surveillance", "reconnaissance", "intel"],
    "cyber": ["cyber", "information warfare", "offensive cyber"],
    "ai": ["ai", "artificial intelligence", "machine learning", "ml"],
    "sensors": ["sensor", "sensing", "detection"],
    "pnt": ["pnt", "navigation", "gps", "positioning"],
    "radar": ["radar", "phased array"],
    "missile defense": ["missile defense", "iamd", "air defense", "amd"],
    "directed energy": ["directed energy", "laser", "hel", "hpm", "de"],
    "autonomy": ["autonomy", "autonomous", "unmanned", "uas", "uav", "drone"],
    "hypersonic": ["hypersonic", "hypersonics"],
}

# Entity type detection patterns
TYPE_PATTERNS = {
    "stakeholder": ["stakeholder", "buyer", "peo", "pm ", "program manager", "acquisition", "acqui", "enabler"],
    "program": ["program", "system", "project"],
    "unit": ["unit", "battalion", "squadron", "wing", "brigade", "division", "regiment"],
    "platform": ["platform", "aircraft", "ship", "vehicle", "submarine"],
    "competitor": ["competitor", "company", "vendor", "contractor"],
    "technology": ["technology", "modality", "tech"],
}


def parse_natural_language_query(query: str) -> Dict[str, Any]:
    """Parse natural language query into structured filters."""
    filters = {}
    query_lower = query.lower()
    remaining_text = query_lower

    # Detect service
    for service, patterns in SERVICE_PATTERNS.items():
        for pattern in patterns:
            if pattern in query_lower:
                filters["service"] = service.title() if service not in ["darpa", "socom", "cybercom"] else service.upper()
                remaining_text = remaining_text.replace(pattern, "")
                break
        if "service" in filters:
            break

    # Detect domain
    for domain, patterns in DOMAIN_PATTERNS.items():
        for pattern in patterns:
            if pattern in query_lower:
                filters["domain"] = domain
                remaining_text = remaining_text.replace(pattern, "")
                break
        if "domain" in filters:
            break

    # Detect entity type
    for entity_type, patterns in TYPE_PATTERNS.items():
        for pattern in patterns:
            if pattern in query_lower:
                filters["entity_type"] = entity_type
                remaining_text = remaining_text.replace(pattern, "")
                break
        if "entity_type" in filters:
            break

    # Clean up remaining text for full-text search
    remaining_text = re.sub(r'\s+', ' ', remaining_text).strip()
    if remaining_text and len(remaining_text) > 2:
        filters["text"] = remaining_text

    return filters


def score_entity_relevance(entity: Entity, query_filters: Dict[str, Any]) -> float:
    """Calculate relevance score for an entity based on query filters."""
    score = 0.0

    # Service match
    if "service" in query_filters:
        if entity.service and query_filters["service"].lower() in entity.service.lower():
            score += 2.0

    # Domain match
    if "domain" in query_filters:
        domain_filter = query_filters["domain"].lower()
        if entity.domain and domain_filter in entity.domain.lower():
            score += 2.0
        # Check tags
        for tag in entity.tags:
            if domain_filter in tag.lower():
                score += 1.0
                break

    # Entity type match
    if "entity_type" in query_filters:
        entity_type = entity.entity_type
        if isinstance(entity_type, EntityType):
            entity_type = entity_type.value
        if entity_type == query_filters["entity_type"]:
            score += 2.0

    # Text match (title is most important)
    if "text" in query_filters:
        text_filter = query_filters["text"].lower()
        if text_filter in entity.title.lower():
            score += 5.0
        elif entity.summary and text_filter in entity.summary.lower():
            score += 2.0
        elif text_filter in entity.content.lower():
            score += 1.0

    return score


def search_entities(entities: List[Entity], query: str, limit: int = 50) -> List[SearchResult]:
    """Search entities with natural language query parsing."""
    # Parse query into filters
    filters = parse_natural_language_query(query)

    # If no filters extracted, use raw query as text search
    if not filters:
        filters["text"] = query.lower()

    # Score and filter entities
    results = []
    for entity in entities:
        score = score_entity_relevance(entity, filters)
        if score > 0:
            results.append(SearchResult(
                entity=entity,
                score=score,
                match_type="combined"
            ))

    # Sort by score and limit
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]


def get_search_suggestions(query: str) -> List[str]:
    """Get query suggestions based on partial input."""
    suggestions = []

    # Suggest services
    for service in SERVICE_PATTERNS.keys():
        if query.lower() in service:
            suggestions.append(f"{service.title()} buyers")
            suggestions.append(f"{service.title()} programs")

    # Suggest domains
    for domain in DOMAIN_PATTERNS.keys():
        if query.lower() in domain:
            suggestions.append(f"{domain} programs")
            suggestions.append(f"{domain} systems")

    return suggestions[:5]
