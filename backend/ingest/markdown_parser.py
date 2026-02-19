"""Markdown parsing and entity extraction from Obsidian vault."""
import re
import frontmatter
from pathlib import Path
from typing import List, Dict, Any, Optional
import yaml

from backend.models.entities import (
    Entity, EntityType, Stakeholder, Program, Platform,
    Company, Unit, Technology,
    CongressMember, CongressCommittee, ExecutiveOfficial, ExecutiveOffice
)


def extract_wiki_links(content: str) -> List[str]:
    """Extract [[wiki-links]] from markdown content."""
    pattern = r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]'
    matches = re.findall(pattern, content)
    return list(set(matches))


def extract_summary(content: str, max_length: int = 300) -> str:
    """Extract first meaningful paragraph as summary."""
    # Skip headers and empty lines
    lines = content.split('\n')
    summary_lines = []

    for line in lines:
        stripped = line.strip()
        # Skip headers, empty lines, tables, and frontmatter markers
        if stripped and not stripped.startswith('#') and not stripped.startswith('|') \
           and not stripped.startswith('---') and not stripped.startswith('-'):
            summary_lines.append(stripped)
            if len(' '.join(summary_lines)) > max_length:
                break

    summary = ' '.join(summary_lines)[:max_length]
    if len(' '.join(summary_lines)) > max_length:
        summary = summary.rsplit(' ', 1)[0] + '...'
    return summary


def detect_entity_type(file_path: Path, tags: List[str], metadata: Dict) -> EntityType:
    """Detect entity type from file path, tags, and metadata.

    New vault structure:
    - Organizations/[Service]/Programs/ -> PROGRAM
    - Organizations/[Service]/Stakeholders/Requirements/ -> STAKEHOLDER (requirements generators)
    - Organizations/[Service]/Stakeholders/Enablers/ -> STAKEHOLDER (R&D, test, acquisition orgs)
    - Organizations/[Service]/Units/ -> UNIT
    - Organizations/Congress/ -> CONGRESS_MEMBER or CONGRESS_COMMITTEE
    - Organizations/Executive-Branch/ -> EXECUTIVE_OFFICIAL or EXECUTIVE_OFFICE

    Both Requirements and Enablers in Stakeholders/ use the same schema with
    stakeholder_type field to distinguish them. They share fields like category,
    parent_org, etc. that are specific to the stakeholder entity type.
    """
    # Normalize path separators to forward slashes for consistent matching
    path_str = str(file_path).lower().replace('\\', '/')
    tags_lower = [t.lower() for t in tags]
    tags_str = ' '.join(tags_lower)

    # PRIORITY: Check for Stakeholders structure FIRST (path takes precedence)
    # Both Enablers and Requirements in Stakeholders/ are STAKEHOLDER type
    # They use stakeholder_type field to distinguish (Enabler vs Requirements)
    if '/stakeholders/enablers/' in path_str:
        return EntityType.STAKEHOLDER
    if '/stakeholders/requirements/' in path_str:
        return EntityType.STAKEHOLDER

    # Check explicit metadata (only if not in Stakeholders/ paths)
    if metadata.get('organization_type', '').lower() == 'buyer':
        return EntityType.STAKEHOLDER
    if metadata.get('organization_type', '').lower() == 'stakeholder':
        return EntityType.STAKEHOLDER
    if metadata.get('organization_type', '').lower() == 'enabler':
        return EntityType.STAKEHOLDER
    if metadata.get('organization_type', '').lower() == 'requirements':
        return EntityType.UNIT

    # Political Affairs detection - check tags and path
    # Congress members: tags contain congress/senate or congress/house + member
    is_congress = 'congress/senate' in tags_str or 'congress/house' in tags_str or 'congress' in path_str
    is_member = 'member' in tags_lower or '/members/' in path_str.lower()
    is_committee = 'committee' in tags_lower or '/committees/' in path_str.lower()
    is_executive = 'executive-branch' in tags_str or 'executive-branch' in path_str
    is_official = 'official' in tags_lower or 'priority-target' in tags_str

    if is_congress and is_committee:
        return EntityType.CONGRESS_COMMITTEE
    if is_congress and is_member:
        return EntityType.CONGRESS_MEMBER
    if is_executive and is_official:
        return EntityType.EXECUTIVE_OFFICIAL
    if is_executive and not is_official:
        # Check if it's an office file (overview, main org file)
        file_name = file_path.stem.lower()
        if 'overview' in file_name or file_name in ['ostp', 'nsc', 'omb', 'ntia', 'odni', 'dhs']:
            return EntityType.EXECUTIVE_OFFICE
        # If it's in executive-branch but not an overview, likely an official
        return EntityType.EXECUTIVE_OFFICIAL

    # Check path-based detection for Programs
    if '/programs/' in path_str or 'program' in tags_lower:
        return EntityType.PROGRAM

    # Check for Units folder
    if '/units/' in path_str:
        return EntityType.UNIT

    # Legacy: check for old Buyers folder (for backwards compatibility)
    if '/buyers/' in path_str:
        return EntityType.STAKEHOLDER

    # Legacy: Operational-Units folder
    if 'operational' in path_str:
        return EntityType.UNIT

    if 'platforms' in path_str or 'platform' in tags_lower:
        return EntityType.PLATFORM
    if 'companies' in path_str or 'company' in tags_lower or 'competitor' in tags_lower or 'partner' in tags_lower:
        return EntityType.COMPANY
    if 'technology' in path_str or 'modalities' in path_str:
        return EntityType.TECHNOLOGY
    if 'systems' in path_str or 'system' in tags_lower:
        return EntityType.SYSTEM
    if 'moc' in path_str or 'moc' in tags_lower:
        return EntityType.MOC

    # Tag-based detection
    if 'buyer' in tags_lower or 'enabler' in tags_lower or 'stakeholder' in tags_lower or 'organization' in tags_lower:
        return EntityType.STAKEHOLDER
    if 'program' in tags_lower:
        return EntityType.PROGRAM
    if 'requirements' in tags_lower or 'operational_unit' in tags_lower or 'unit' in tags_lower:
        return EntityType.UNIT

    return EntityType.UNKNOWN


def detect_chamber(file_path: Path, tags: List[str]) -> Optional[str]:
    """Detect congressional chamber from file path and tags."""
    path_str = str(file_path).lower()
    tags_str = ' '.join([t.lower() for t in tags])

    if 'senate' in path_str or 'congress/senate' in tags_str:
        return 'Senate'
    if 'house' in path_str or 'congress/house' in tags_str:
        return 'House'
    return None


def get_platform_image_url(title: str) -> Optional[str]:
    """Generate the image URL for a platform based on its title.

    Images are stored as lowercase PNG files in /assets/platforms/
    The filename is derived from the platform title with spaces converted to hyphens.
    """
    # Convert title to filename format: lowercase, spaces to hyphens
    filename = title.lower().replace(' ', '-').replace('/', '-')
    # Remove special characters except hyphens
    filename = ''.join(c for c in filename if c.isalnum() or c == '-')
    return f"/assets/platforms/{filename}.png"


def detect_executive_org(file_path: Path, tags: List[str]) -> Optional[str]:
    """Detect executive branch organization from file path."""
    path_str = str(file_path)

    # Extract organization from path like Executive-Branch/White-House/OSTP.md
    if 'executive-branch' in path_str.lower():
        parts = path_str.split('Executive-Branch')
        if len(parts) > 1:
            org_parts = parts[1].strip('/\\').split('/')
            if len(org_parts) > 0:
                return org_parts[0].replace('-', ' ')
    return None


def detect_service(file_path: Path, tags: List[str], metadata: Dict) -> Optional[str]:
    """Detect military service from file path, tags, and metadata.

    Service/Organization mappings for vault structure:
    - Organizations/DoD/ -> DoD (department-wide orgs like S&T, OUSD-R&E)
    - Organizations/Army/, Navy/, Air-Force/, Space-Force/, USMC/
    - Organizations/SOCOM/, Joint/, OSD/, DARPA/, CYBERCOM/
    - Organizations/COCOMs/, Congress/, Executive-Branch/, OTA-Consortiums/, DOE/

    IMPORTANT: Service is determined by the FIRST organization-level folder after
    "Organizations/", not by subfolders deeper in the path. For example:
    - Organizations/DoD/Stakeholders/Enablers/S-T/Army/ARL-ESS.md -> DoD (not Army)
    - Organizations/Army/Stakeholders/Enablers/DEVCOM/ARL.md -> Army
    """
    # Check metadata first
    if 'service' in metadata:
        svc = metadata['service']
        # Normalize Marines -> USMC
        if svc in ['Marines', 'Marine Corps']:
            return 'USMC'
        return svc
    if 'domain' in metadata:
        domain = metadata['domain']
        if isinstance(domain, str):
            for svc in ['Army', 'Navy', 'USMC', 'Air Force', 'Space Force', 'SOCOM']:
                if svc.lower() in domain.lower():
                    return svc
            # Check for Marines -> USMC
            if 'marine' in domain.lower():
                return 'USMC'

    path_str = str(file_path).replace('\\', '/')
    path_lower = path_str.lower()
    tags_lower = [t.lower() for t in tags]

    # Service map - maps folder names to display names
    service_map = {
        # DoD-wide (must check first)
        'dod': 'DoD',
        # Primary services
        'army': 'Army',
        'navy': 'Navy',
        'usmc': 'USMC',
        'marines': 'USMC',
        'marine': 'USMC',
        'air-force': 'Air Force',
        'airforce': 'Air Force',
        'space-force': 'Space Force',
        'spaceforce': 'Space Force',
        # Commands and agencies
        'socom': 'SOCOM',
        'joint': 'Joint',
        'osd': 'OSD',
        'darpa': 'DARPA',
        'cybercom': 'CYBERCOM',
        # Other organizational types
        'cocoms': 'COCOMs',
        'congress': 'Congress',
        'executive-branch': 'Executive Branch',
        'ota-consortiums': 'OTA Consortiums',
        'doe': 'DOE',
    }

    # Find the service from path - look for Organizations/[Service]/ pattern
    # The service is the FIRST folder after "Organizations/"
    path_parts = path_str.split('/')
    if 'Organizations' in path_parts:
        org_idx = path_parts.index('Organizations')
        if len(path_parts) > org_idx + 1:
            # Get the folder immediately after Organizations/
            service_folder = path_parts[org_idx + 1]
            service_folder_lower = service_folder.lower()
            # Check if it matches a known service mapping
            if service_folder_lower in service_map:
                return service_map[service_folder_lower]
            # Also check with hyphen normalization
            service_folder_normalized = service_folder_lower.replace('-', '')
            for key, value in service_map.items():
                if service_folder_normalized == key.replace('-', ''):
                    return value
            # If not in map, use the folder name directly (preserving case)
            # This handles COCOMs like AFRICOM, CENTCOM, EUCOM, etc.
            return service_folder

    # Fallback: check tags
    for tag in tags_lower:
        for key, value in service_map.items():
            if key in tag:
                return value

    return None


def parse_markdown_file(file_path: Path, vault_path: Path) -> Entity:
    """Parse a single markdown file into an Entity."""
    with open(file_path, 'r', encoding='utf-8') as f:
        post = frontmatter.load(f)

    relative_path = str(file_path.relative_to(vault_path))
    entity_id = relative_path.replace('\\', '/').replace('.md', '')

    tags = post.get('tags', [])
    if isinstance(tags, str):
        tags = [tags]

    metadata = dict(post.metadata)

    # Detect entity properties
    entity_type = detect_entity_type(file_path, tags, metadata)
    service = detect_service(file_path, tags, metadata)

    # Extract content and links
    content = post.content
    links = extract_wiki_links(content)
    summary = extract_summary(content)

    # Extract title: prefer 'title' frontmatter, then 'full_name', then H1 heading, then filename
    title = post.get('title')
    if not title:
        title = post.get('full_name')
    if not title:
        # Try to find H1 heading in content
        for line in content.split('\n'):
            if line.startswith('# '):
                title = line[2:].strip()
                break
    if not title:
        title = file_path.stem.replace('-', ' ')

    # Create base entity data
    entity_data = {
        'id': entity_id,
        'title': title,
        'entity_type': entity_type,
        'service': service,
        'domain': metadata.get('domain'),
        'tags': tags,
        'content': content,
        'summary': summary,
        'links': links,
        'backlinks': [],  # Populated later
        'file_path': relative_path,
        'metadata': metadata,
    }

    # Create type-specific entities
    if entity_type == EntityType.STAKEHOLDER:
        return Stakeholder(
            **entity_data,
            parent_org=metadata.get('parent_org', '').replace('[[', '').replace(']]', ''),
            category=metadata.get('category'),
        )
    elif entity_type == EntityType.PROGRAM:
        return Program(
            **entity_data,
            program_office=metadata.get('program_office', '').replace('[[', '').replace(']]', ''),
            status=metadata.get('status'),
            budget=metadata.get('budget'),
            contractor=metadata.get('contractor'),
        )
    elif entity_type == EntityType.PLATFORM:
        return Platform(
            **entity_data,
            platform_type=metadata.get('platform_type'),
            program_office=metadata.get('program_office', '').replace('[[', '').replace(']]', ''),
            platform_count=metadata.get('platform_count'),
            unit_cost=metadata.get('unit_cost'),
            contractor=metadata.get('contractor'),
            image_url=get_platform_image_url(entity_data['title']),
        )
    elif entity_type == EntityType.COMPANY:
        return Company(
            **entity_data,
            location=metadata.get('location'),
            founded=metadata.get('founded'),
            valuation=metadata.get('valuation'),
            threat_level=metadata.get('threat_level'),
            relationship=metadata.get('relationship'),
        )
    elif entity_type == EntityType.UNIT:
        return Unit(
            **entity_data,
            unit_type=metadata.get('unit_type'),
            location=metadata.get('location'),
            parent_command=metadata.get('parent_command'),
            mission=metadata.get('mission'),
        )
    elif entity_type == EntityType.TECHNOLOGY:
        return Technology(
            **entity_data,
            modality=metadata.get('modality'),
        )
    elif entity_type == EntityType.CONGRESS_MEMBER:
        chamber = detect_chamber(file_path, tags)
        # Parse committees from metadata (may be list or string)
        committees = metadata.get('committees', [])
        if isinstance(committees, str):
            committees = [c.strip() for c in committees.split(',')]
        # Parse roles
        roles = metadata.get('roles', [])
        if isinstance(roles, str):
            roles = [r.strip() for r in roles.split(',')]
        return CongressMember(
            **entity_data,
            party=metadata.get('party'),
            state=metadata.get('state'),
            district=metadata.get('district'),
            chamber=chamber,
            committees=committees,
            roles=roles,
            military=metadata.get('military'),
            priority=metadata.get('priority', False),
        )
    elif entity_type == EntityType.CONGRESS_COMMITTEE:
        chamber = detect_chamber(file_path, tags)
        # Determine committee type from tags
        tags_lower = [t.lower() for t in tags]
        committee_type = None
        if 'authorization' in tags_lower:
            committee_type = 'authorization'
        elif 'appropriations' in tags_lower:
            committee_type = 'appropriations'
        elif 'intelligence' in tags_lower:
            committee_type = 'intelligence'
        return CongressCommittee(
            **entity_data,
            chamber=chamber,
            committee_type=committee_type,
            member_count=metadata.get('member_count'),
            jurisdiction=metadata.get('jurisdiction'),
        )
    elif entity_type == EntityType.EXECUTIVE_OFFICIAL:
        organization = detect_executive_org(file_path, tags)
        return ExecutiveOfficial(
            **entity_data,
            organization=organization,
            office=metadata.get('office'),
            tier=metadata.get('tier'),
            priority=metadata.get('priority', False),
        )
    elif entity_type == EntityType.EXECUTIVE_OFFICE:
        organization = detect_executive_org(file_path, tags)
        return ExecutiveOffice(
            **entity_data,
            organization=organization,
            full_name=metadata.get('full_name'),
            mission=metadata.get('mission'),
        )
    else:
        return Entity(**entity_data)


def parse_vault(vault_path: Path) -> List[Entity]:
    """Parse all markdown files in vault."""
    entities = []
    vault_path = Path(vault_path)

    for md_file in vault_path.rglob("*.md"):
        path_str = str(md_file).replace('\\', '/')

        # Skip template files, temp files, and reference files
        if 'Templates' in path_str or 'tmpclaude' in path_str:
            continue
        # Skip Reference folder (contains data sources, not primary entities)
        if '/Reference/' in path_str:
            continue
        # Skip MOC files
        filename_lower = md_file.stem.lower()
        if filename_lower.startswith('moc-') or filename_lower.startswith('moc_'):
            continue
        if '/MOCs/' in path_str or '/mocs/' in path_str:
            continue
        # Skip summary and landscape files
        if 'summary' in filename_lower or 'landscape' in filename_lower:
            continue

        try:
            entity = parse_markdown_file(md_file, vault_path)
            entities.append(entity)
        except Exception as e:
            print(f"Error parsing {md_file}: {e}")
            continue

    # Build backlinks
    entity_map = {e.id: e for e in entities}
    title_to_id = {}
    for e in entities:
        # Map various forms of the title to the entity ID
        title_to_id[e.title.lower()] = e.id
        title_to_id[e.id.split('/')[-1].lower()] = e.id

    for entity in entities:
        for link in entity.links:
            # Try to resolve link to entity ID
            link_lower = link.lower()
            target_id = title_to_id.get(link_lower)
            if target_id and target_id in entity_map:
                target_entity = entity_map[target_id]
                if entity.id not in target_entity.backlinks:
                    target_entity.backlinks.append(entity.id)

    return entities


if __name__ == "__main__":
    # Test parsing
    vault_path = Path(__file__).parent.parent.parent.parent / "jcs-remote" / "Distributed"
    entities = parse_vault(vault_path)
    print(f"Parsed {len(entities)} entities")

    # Print type distribution
    from collections import Counter
    type_counts = Counter(e.entity_type for e in entities)
    for entity_type, count in type_counts.most_common():
        print(f"  {entity_type}: {count}")
