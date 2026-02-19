"""Entity editing and serialization for syncing changes back to vault markdown files."""
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
import frontmatter
from pydantic import BaseModel


# Field type definitions
class FieldDefinition(BaseModel):
    """Definition for an editable field."""
    name: str
    label: str
    type: str  # text, textarea, select, multiselect, tags, wikilink, wikilinks
    required: bool = False
    options: Optional[List[str]] = None
    section: str = "frontmatter"  # frontmatter or content
    placeholder: Optional[str] = None


class FieldSchema(BaseModel):
    """Schema for entity editing."""
    fields: List[FieldDefinition]


class EntityUpdateRequest(BaseModel):
    """Request body for entity updates."""
    # Common fields
    title: Optional[str] = None
    tags: Optional[List[str]] = None
    service: Optional[str] = None
    domain: Optional[str] = None

    # Frontmatter fields (will be merged into metadata)
    metadata_updates: Optional[Dict[str, Any]] = None

    # Content sections
    overview: Optional[str] = None
    mission: Optional[str] = None
    additional_notes: Optional[str] = None


class EntityUpdateResponse(BaseModel):
    """Response from entity update."""
    success: bool
    entity_id: str
    warnings: List[str] = []
    message: str = ""


# Service options
SERVICE_OPTIONS = [
    "Army", "Navy", "USMC", "Marines", "Air Force", "Space Force",
    "SOCOM", "Joint", "OSD", "DARPA", "CYBERCOM", "Coast Guard"
]

# COCOM options
COCOM_OPTIONS = [
    "INDOPACOM", "EUCOM", "CENTCOM", "AFRICOM", "NORTHCOM",
    "SOUTHCOM", "SPACECOM", "CYBERCOM", "TRANSCOM", "STRATCOM", "CONUS"
]

# Program status options
PROGRAM_STATUS_OPTIONS = [
    "Pre-MS A", "MS A", "MS B", "MS C", "EMD", "LRIP", "FRP",
    "IOC", "FOC", "Sustainment", "Strategic Realignment"
]

# Buyer category options
BUYER_CATEGORY_OPTIONS = [
    "PEO", "PM", "PdM", "DASA", "Secretariat", "Lab", "Test Range",
    "Command", "Center", "Directorate"
]


# Stakeholder category options (from templates)
STAKEHOLDER_CATEGORY_OPTIONS = [
    "Research", "T&E", "Training", "Intelligence", "C4", "Cyber", "Operations"
]

# ACAT level options
ACAT_OPTIONS = ["ACAT I", "ACAT IC", "ACAT ID", "ACAT II", "ACAT III", "MTA", "Other"]

# Field schemas by entity type
ENTITY_FIELD_SCHEMAS: Dict[str, FieldSchema] = {
    # Template: Template-Unit.md
    "unit": FieldSchema(fields=[
        FieldDefinition(name="title", label="Name", type="text", required=True),
        FieldDefinition(name="full_name", label="Full Name", type="text", section="frontmatter"),
        FieldDefinition(name="service", label="Service", type="select", options=SERVICE_OPTIONS),
        FieldDefinition(name="domain", label="Domain", type="text"),
        FieldDefinition(name="component_type", label="Component Type", type="text", section="frontmatter"),
        FieldDefinition(name="location", label="Location", type="text", section="frontmatter"),
        FieldDefinition(name="parent", label="Parent Command", type="wikilink", section="frontmatter"),
        FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
        FieldDefinition(name="mission", label="Mission", type="textarea", section="content"),
        FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
        FieldDefinition(name="tags", label="Tags", type="tags"),
    ]),
    # Template: Template-Program.md
    "program": FieldSchema(fields=[
        FieldDefinition(name="title", label="Name", type="text", required=True),
        FieldDefinition(name="domain", label="Domain", type="text"),
        FieldDefinition(name="service", label="Service", type="select", options=SERVICE_OPTIONS),
        FieldDefinition(name="peo", label="PEO", type="text", section="frontmatter"),
        FieldDefinition(name="acat", label="ACAT Level", type="select", options=ACAT_OPTIONS, section="frontmatter"),
        FieldDefinition(name="status", label="Status", type="select", options=PROGRAM_STATUS_OPTIONS, section="frontmatter"),
        FieldDefinition(name="contractor", label="Prime Contractor", type="text", section="frontmatter"),
        FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
        FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
        FieldDefinition(name="tags", label="Tags", type="tags"),
    ]),
    # Template: Template-Enabler-Child.md / Template-Requirements-Child.md
    "stakeholder": FieldSchema(fields=[
        FieldDefinition(name="title", label="Name", type="text", required=True),
        FieldDefinition(name="domain", label="Domain", type="text"),
        FieldDefinition(name="organization_type", label="Organization Type", type="text", section="frontmatter"),
        FieldDefinition(name="stakeholder_type", label="Stakeholder Type", type="select", options=["Enabler", "Requirements"], section="frontmatter"),
        FieldDefinition(name="category", label="Category", type="select", options=STAKEHOLDER_CATEGORY_OPTIONS, section="frontmatter"),
        FieldDefinition(name="parent_org", label="Parent Organization", type="wikilink", section="frontmatter"),
        FieldDefinition(name="location", label="Location", type="text", section="frontmatter"),
        FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
        FieldDefinition(name="mission", label="Mission", type="textarea", section="content"),
        FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
        FieldDefinition(name="tags", label="Tags", type="tags"),
    ]),
    # Template: Template-Platform.md
    "platform": FieldSchema(fields=[
        FieldDefinition(name="title", label="Name", type="text", required=True),
        FieldDefinition(name="domain", label="Domain", type="text"),
        FieldDefinition(name="service", label="Service", type="select", options=SERVICE_OPTIONS),
        FieldDefinition(name="program_office", label="Program Office", type="wikilink", section="frontmatter"),
        FieldDefinition(name="platform_count", label="Platform Count", type="text", section="frontmatter"),
        FieldDefinition(name="unit_cost", label="Unit Cost", type="text", section="frontmatter"),
        FieldDefinition(name="program_budget", label="Program Budget", type="text", section="frontmatter"),
        FieldDefinition(name="production_rate", label="Production Rate", type="text", section="frontmatter"),
        FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
        FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
        FieldDefinition(name="tags", label="Tags", type="tags"),
    ]),
    # Template: Template-Company.md
    "competitor": FieldSchema(fields=[
        FieldDefinition(name="title", label="Name", type="text", required=True),
        FieldDefinition(name="type", label="Type", type="select", options=["Startup", "Prime"], section="frontmatter"),
        FieldDefinition(name="relationship", label="Relationship", type="select", options=["Competitor", "Partner", "Adjacent", "Watch"], section="frontmatter"),
        FieldDefinition(name="threat_level", label="Threat Level", type="select", options=["High", "Medium", "Low"], section="frontmatter"),
        FieldDefinition(name="location", label="Location", type="text", section="frontmatter"),
        FieldDefinition(name="revenue", label="Revenue", type="text", section="frontmatter"),
        FieldDefinition(name="employees", label="Employees", type="text", section="frontmatter"),
        FieldDefinition(name="funding", label="Funding", type="text", section="frontmatter"),
        FieldDefinition(name="natsec100_rank", label="NatSec100 Rank", type="text", section="frontmatter"),
        FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
        FieldDefinition(name="key_insight", label="Key Insight", type="textarea", section="content"),
        FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
        FieldDefinition(name="tags", label="Tags", type="tags"),
    ]),
    # Template: Template-Company.md (alias for competitor)
    "company": FieldSchema(fields=[
        FieldDefinition(name="title", label="Name", type="text", required=True),
        FieldDefinition(name="type", label="Type", type="select", options=["Startup", "Prime"], section="frontmatter"),
        FieldDefinition(name="relationship", label="Relationship", type="select", options=["Competitor", "Partner", "Adjacent", "Watch"], section="frontmatter"),
        FieldDefinition(name="threat_level", label="Threat Level", type="select", options=["High", "Medium", "Low"], section="frontmatter"),
        FieldDefinition(name="location", label="Location", type="text", section="frontmatter"),
        FieldDefinition(name="revenue", label="Revenue", type="text", section="frontmatter"),
        FieldDefinition(name="employees", label="Employees", type="text", section="frontmatter"),
        FieldDefinition(name="funding", label="Funding", type="text", section="frontmatter"),
        FieldDefinition(name="natsec100_rank", label="NatSec100 Rank", type="text", section="frontmatter"),
        FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
        FieldDefinition(name="key_insight", label="Key Insight", type="textarea", section="content"),
        FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
        FieldDefinition(name="tags", label="Tags", type="tags"),
    ]),
    # Template: Template-Technology-Modality.md
    "technology": FieldSchema(fields=[
        FieldDefinition(name="title", label="Name", type="text", required=True),
        FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
        FieldDefinition(name="key_insight", label="Key Insight", type="textarea", section="content"),
        FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
        FieldDefinition(name="tags", label="Tags", type="tags"),
    ]),
    # Template: Template-Congress-Member.md
    "congress_member": FieldSchema(fields=[
        FieldDefinition(name="title", label="Name", type="text", required=True),
        FieldDefinition(name="party", label="Party", type="select", options=["D", "R", "I"], section="frontmatter"),
        FieldDefinition(name="state", label="State", type="text", section="frontmatter"),
        FieldDefinition(name="district", label="District", type="text", section="frontmatter"),
        FieldDefinition(name="chamber", label="Chamber", type="select", options=["House", "Senate"], section="frontmatter"),
        FieldDefinition(name="military", label="Military Background", type="text", section="frontmatter"),
        FieldDefinition(name="committees", label="Committees", type="tags", section="frontmatter"),
        FieldDefinition(name="roles", label="Roles", type="tags", section="frontmatter"),
        FieldDefinition(name="priority", label="Priority Target", type="select", options=["true", "false"], section="frontmatter"),
        FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
        FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
        FieldDefinition(name="tags", label="Tags", type="tags"),
    ]),
    # Template: Template-Executive-Branch-Official.md
    "executive_official": FieldSchema(fields=[
        FieldDefinition(name="title", label="Name", type="text", required=True),
        FieldDefinition(name="priority", label="Priority Target", type="select", options=["true", "false"], section="frontmatter"),
        FieldDefinition(name="tier", label="Tier", type="select", options=["1", "2"], section="frontmatter"),
        FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
        FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
        FieldDefinition(name="tags", label="Tags", type="tags"),
    ]),
    # Template: Template-Executive-Branch-Organization.md
    "executive_office": FieldSchema(fields=[
        FieldDefinition(name="title", label="Name", type="text", required=True),
        FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
        FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
        FieldDefinition(name="tags", label="Tags", type="tags"),
    ]),
    # Template: Template-Congress-Committee.md
    "congress_committee": FieldSchema(fields=[
        FieldDefinition(name="title", label="Name", type="text", required=True),
        FieldDefinition(name="domain", label="Domain", type="text"),
        FieldDefinition(name="chamber", label="Chamber", type="select", options=["Senate", "House"], section="frontmatter"),
        FieldDefinition(name="organization_type", label="Organization Type", type="text", section="frontmatter"),
        FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
        FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
        FieldDefinition(name="tags", label="Tags", type="tags"),
    ]),
}

# Default schema for unknown entity types
DEFAULT_FIELD_SCHEMA = FieldSchema(fields=[
    FieldDefinition(name="title", label="Name", type="text", required=True),
    FieldDefinition(name="service", label="Service", type="select", options=SERVICE_OPTIONS),
    FieldDefinition(name="domain", label="Domain", type="text"),
    FieldDefinition(name="overview", label="Overview", type="textarea", section="content"),
    FieldDefinition(name="notes", label="Notes", type="textarea", section="content", placeholder="Add notes here..."),
    FieldDefinition(name="tags", label="Tags", type="tags"),
])


def get_field_schema(entity_type: str) -> FieldSchema:
    """Get the field schema for an entity type."""
    return ENTITY_FIELD_SCHEMAS.get(entity_type, DEFAULT_FIELD_SCHEMA)


def extract_content_section(content: str, section_name: str) -> Optional[str]:
    """Extract content from a markdown section (## Section Name)."""
    # Pattern to match section header and content until next section or end
    pattern = rf'^## {re.escape(section_name)}\s*\n(.*?)(?=^## |\Z)'
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def update_content_section(content: str, section_name: str, new_content: str) -> str:
    """Update or add a content section in markdown."""
    # Pattern to match section header and content until next section or end
    pattern = rf'(^## {re.escape(section_name)}\s*\n)(.*?)(?=^## |\Z)'

    def replacement(match):
        return match.group(1) + new_content + '\n\n'

    new_markdown, count = re.subn(pattern, replacement, content, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)

    if count == 0:
        # Section doesn't exist, add it at the end
        new_markdown = content.rstrip() + f'\n\n## {section_name}\n{new_content}\n'

    return new_markdown


def format_wiki_link(value: str) -> str:
    """Format a value as a wiki link if not already formatted."""
    if not value:
        return value
    value = value.strip()
    if value.startswith('[[') and value.endswith(']]'):
        return value
    return f'[[{value}]]'


def format_wiki_links_list(values: List[str]) -> List[str]:
    """Format a list of values as wiki links."""
    return [format_wiki_link(v) for v in values if v]


def strip_wiki_link(value: str) -> str:
    """Remove wiki link formatting from a value."""
    if not value:
        return value
    return value.replace('[[', '').replace(']]', '').strip()


def serialize_entity_to_markdown(
    existing_content: str,
    existing_metadata: Dict[str, Any],
    updates: Dict[str, Any],
    entity_type: str
) -> str:
    """
    Serialize entity updates back to markdown format.

    Merges updates with existing content and metadata,
    then reconstructs the markdown file.
    """
    schema = get_field_schema(entity_type)

    # Start with existing metadata
    new_metadata = dict(existing_metadata)
    new_content = existing_content

    # Process each field in the update
    for field in schema.fields:
        field_name = field.name
        if field_name not in updates:
            continue

        value = updates[field_name]

        if field.section == "frontmatter":
            # Update frontmatter field
            if field.type == "wikilink" and value:
                # Single wiki link
                new_metadata[field_name] = format_wiki_link(value)
            elif field.type == "wikilinks" and value:
                # List of wiki links
                if isinstance(value, list):
                    new_metadata[field_name] = format_wiki_links_list(value)
                else:
                    new_metadata[field_name] = format_wiki_links_list([value])
            elif field.type == "tags" and value:
                # Tags go in metadata
                new_metadata['tags'] = value if isinstance(value, list) else [value]
            else:
                # Regular field
                if value is not None:
                    new_metadata[field_name] = value
                elif field_name in new_metadata:
                    del new_metadata[field_name]

        elif field.section == "content":
            # Update content section
            if value is not None:
                section_name = field.label  # Use label as section header
                new_content = update_content_section(new_content, section_name, value)

    # Handle title specially (goes in frontmatter)
    if 'title' in updates and updates['title']:
        new_metadata['title'] = updates['title']

    # Handle top-level fields (service, domain, tags)
    if 'service' in updates:
        new_metadata['service'] = updates['service']
    if 'domain' in updates:
        new_metadata['domain'] = updates['domain']
    if 'tags' in updates:
        new_metadata['tags'] = updates['tags']

    # Create the markdown file with frontmatter
    post = frontmatter.Post(new_content)
    post.metadata = new_metadata

    return frontmatter.dumps(post)


def read_entity_file(vault_path: Path, file_path: str) -> tuple[Dict[str, Any], str]:
    """
    Read an entity's markdown file and return metadata and content.

    Args:
        vault_path: Path to the vault root
        file_path: Relative path to the entity file (with .md extension)

    Returns:
        Tuple of (metadata dict, content string)
    """
    full_path = vault_path / file_path

    if not full_path.exists():
        raise FileNotFoundError(f"Entity file not found: {full_path}")

    with open(full_path, 'r', encoding='utf-8') as f:
        post = frontmatter.load(f)

    return dict(post.metadata), post.content


def write_entity_file(vault_path: Path, file_path: str, content: str) -> None:
    """
    Write content to an entity's markdown file.

    Args:
        vault_path: Path to the vault root
        file_path: Relative path to the entity file (with .md extension)
        content: Full markdown content including frontmatter
    """
    full_path = vault_path / file_path

    # Ensure parent directory exists
    full_path.parent.mkdir(parents=True, exist_ok=True)

    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)


def validate_wiki_links(links: List[str], db) -> List[str]:
    """
    Validate that wiki links point to existing entities.

    Returns list of invalid links (links to entities that don't exist).
    """
    invalid_links = []

    for link in links:
        # Strip wiki link formatting
        entity_ref = strip_wiki_link(link)
        if not entity_ref:
            continue

        # Try to find the entity
        # First try as direct ID
        entity = db.get_entity(entity_ref)
        if not entity:
            # Try searching by title
            results = db.search(entity_ref, limit=1)
            if not results or results[0].entity.title.lower() != entity_ref.lower():
                invalid_links.append(link)

    return invalid_links


def extract_all_wiki_links(updates: Dict[str, Any], schema: FieldSchema) -> List[str]:
    """Extract all wiki links from update data."""
    links = []

    for field in schema.fields:
        if field.type not in ('wikilink', 'wikilinks'):
            continue

        value = updates.get(field.name)
        if not value:
            continue

        if isinstance(value, list):
            links.extend(value)
        else:
            links.append(value)

    return links
