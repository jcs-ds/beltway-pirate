"""Entity models for DoD Intelligence Platform."""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


class EntityType(str, Enum):
    STAKEHOLDER = "stakeholder"  # Renamed from BUYER
    PROGRAM = "program"
    UNIT = "unit"  # Renamed from OPERATIONAL_UNIT
    PLATFORM = "platform"
    COMPANY = "company"  # Renamed from COMPETITOR
    COMPETITOR = "competitor"  # Legacy alias for COMPANY
    TECHNOLOGY = "technology"
    SYSTEM = "system"
    MOC = "moc"
    # Political Affairs types
    CONGRESS_MEMBER = "congress_member"
    CONGRESS_COMMITTEE = "congress_committee"
    EXECUTIVE_OFFICIAL = "executive_official"
    EXECUTIVE_OFFICE = "executive_office"
    UNKNOWN = "unknown"


class Service(str, Enum):
    """Military services and organizational types."""
    # Primary military services
    ARMY = "Army"
    NAVY = "Navy"
    USMC = "USMC"  # Canonical name (Marines normalized to USMC)
    AIR_FORCE = "Air Force"
    SPACE_FORCE = "Space Force"
    # Commands and agencies
    SOCOM = "SOCOM"
    JOINT = "Joint"
    OSD = "OSD"
    DARPA = "DARPA"
    CYBERCOM = "CYBERCOM"
    # Additional organizational types
    COCOMS = "COCOMs"
    CONGRESS = "Congress"
    EXECUTIVE_BRANCH = "Executive Branch"
    OTA_CONSORTIUMS = "OTA Consortiums"
    DOE = "DOE"
    UNKNOWN = "Unknown"


class Entity(BaseModel):
    """Base entity model for all DoD entities."""
    id: str = Field(..., description="Unique identifier (file path)")
    title: str = Field(..., description="Entity title")
    entity_type: EntityType = Field(default=EntityType.UNKNOWN)
    service: Optional[str] = None
    domain: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    content: str = Field(default="", description="Markdown content")
    summary: Optional[str] = None
    links: List[str] = Field(default_factory=list, description="Wiki-links to other entities")
    backlinks: List[str] = Field(default_factory=list, description="Entities that link to this one")
    file_path: str = Field(..., description="Relative path in vault")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True


class Stakeholder(Entity):
    """Acquisition organization (PEO, PM, etc.). Renamed from Buyer."""
    parent_org: Optional[str] = None
    category: Optional[str] = None
    organization_type: str = "Stakeholder"
    key_contacts: List[Dict[str, str]] = Field(default_factory=list)
    programs: List[str] = Field(default_factory=list)
    contract_vehicles: List[str] = Field(default_factory=list)


class Program(Entity):
    """Acquisition program."""
    program_office: Optional[str] = None
    status: Optional[str] = None  # R&D, EMD, LRIP, FRP, Sustainment
    budget: Optional[str] = None
    contractor: Optional[str] = None
    platforms: List[str] = Field(default_factory=list)
    related_programs: List[str] = Field(default_factory=list)


class Platform(Entity):
    """Military platform (aircraft, ship, vehicle, etc.)."""
    platform_type: Optional[str] = None  # Air, Sea, Land, Space
    program_office: Optional[str] = None
    platform_count: Optional[str] = None
    unit_cost: Optional[str] = None
    contractor: Optional[str] = None
    signatures: Dict[str, str] = Field(default_factory=dict)
    ew_systems: List[str] = Field(default_factory=list)
    image_url: Optional[str] = None  # URL to platform icon image


class Company(Entity):
    """Company (competitor, partner, or adjacent)."""
    location: Optional[str] = None
    founded: Optional[str] = None
    valuation: Optional[str] = None
    threat_level: Optional[str] = None  # Critical, High, Medium, Low
    relationship: Optional[str] = None  # Competitor, Partner, Adjacent, Watch
    products: List[str] = Field(default_factory=list)
    contracts: List[str] = Field(default_factory=list)
    overlap_areas: List[str] = Field(default_factory=list)


class Unit(Entity):
    """Military operational unit. Renamed from OperationalUnit."""
    unit_type: Optional[str] = None
    location: Optional[str] = None
    parent_command: Optional[str] = None
    mission: Optional[str] = None
    systems_used: List[str] = Field(default_factory=list)


class Technology(Entity):
    """Technology modality or system type."""
    modality: Optional[str] = None
    applications: List[str] = Field(default_factory=list)
    related_programs: List[str] = Field(default_factory=list)


class CongressMember(Entity):
    """Congressional member (Senator or Representative)."""
    party: Optional[str] = None  # R, D, I
    state: Optional[str] = None
    district: Optional[str] = None  # For House members
    chamber: Optional[str] = None  # Senate or House
    committees: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)  # Chair, Ranking Member, etc.
    military: Optional[str] = None
    priority: bool = False


class CongressCommittee(Entity):
    """Congressional committee."""
    chamber: Optional[str] = None  # Senate or House
    committee_type: Optional[str] = None  # authorization, appropriations, intelligence
    member_count: Optional[int] = None
    jurisdiction: Optional[str] = None


class ExecutiveOfficial(Entity):
    """Executive branch official."""
    organization: Optional[str] = None  # OSD, White House, DHS, etc.
    office: Optional[str] = None  # OSTP, NSC, OMB, etc.
    title: Optional[str] = None
    tier: Optional[int] = None  # Priority tier 1-2
    priority: bool = False


class ExecutiveOffice(Entity):
    """Executive branch office or agency."""
    organization: Optional[str] = None  # OSD, White House, DHS, etc.
    full_name: Optional[str] = None
    mission: Optional[str] = None


class SearchResult(BaseModel):
    """Search result with relevance scoring."""
    entity: Entity
    score: float = Field(default=0.0)
    highlights: List[str] = Field(default_factory=list)
    match_type: str = Field(default="text")  # text, tag, title, link


class GraphNode(BaseModel):
    """Node in relationship graph."""
    id: str
    title: str
    entity_type: EntityType
    service: Optional[str] = None

    class Config:
        use_enum_values = True


class GraphEdge(BaseModel):
    """Edge in relationship graph."""
    source: str
    target: str
    relationship: str = "links_to"
    weight: float = 1.0


class GraphData(BaseModel):
    """Graph data for visualization."""
    nodes: List[GraphNode]
    edges: List[GraphEdge]
