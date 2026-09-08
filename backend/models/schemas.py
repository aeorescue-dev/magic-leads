from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from datetime import datetime
from typing import Optional, List
from enum import Enum


class SourceType(str, Enum):
    SERVICE_311 = "311"
    BUILDING_PERMIT = "permit"
    TAX_DELINQUENCY = "tax_delinquency"


class IssueCategory(str, Enum):
    ROOF = "Roof"
    PAINT = "Paint"
    PLUMBING = "Plumbing"
    STRUCTURE = "Structure"
    GRASS = "Grass"
    PERMIT_REJECTED = "Permit_Rejected"
    HEATING = "Heating"
    ELECTRICAL = "Electrical"
    ELEVATOR = "Elevator"
    GAS = "Gas"
    RODENT = "Rodent"
    MOLD = "Mold"
    LEAD = "Lead"
    UNSANITARY = "Unsanitary"
    DOOR_WINDOW = "Door_Window"
    DEBRIS = "Debris"


class UrgencyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Raw lead from 311 API
class RawLead311(BaseModel):
    external_id: str
    address: str
    city: str
    state: str
    zip_code: Optional[str]
    issue_description: str
    created_at: datetime
    lat: Optional[float]
    lng: Optional[float]
    issue_category: IssueCategory = IssueCategory.GRASS

    # Historical details from 311 systems (populated generically)
    case_title: Optional[str] = None
    subject: Optional[str] = None
    reason: Optional[str] = None
    type: Optional[str] = None
    queue: Optional[str] = None
    department: Optional[str] = None
    closure_reason: Optional[str] = None
    case_status: Optional[str] = None
    on_time: Optional[str] = None
    sla_target_dt: Optional[str] = None
    closed_dt: Optional[str] = None
    submitted_photo: Optional[str] = None
    closed_photo: Optional[str] = None
    source: Optional[str] = None
    neighborhood: Optional[str] = None
    ward: Optional[str] = None
    precinct: Optional[str] = None
    descriptor: Optional[str] = None
    resolution_description: Optional[str] = None
    resolution_action_updated_date: Optional[str] = None


# Enriched lead (com owner info)
class EnrichedLead(BaseModel):
    external_id: str
    source_type: SourceType
    address: str
    city: str
    state: str
    zip_code: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    county: Optional[str]

    # Address details
    address_unit: Optional[str] = None
    address_type: Optional[str] = None
    address_street: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_zip: Optional[str] = None

    # Issue details (enhanced with historical data)
    issue_category: IssueCategory
    issue_description: str
    urgency_level: UrgencyLevel
    
    # Historical details from 311 systems
    case_title: Optional[str] = None
    subject: Optional[str] = None
    reason: Optional[str] = None
    type: Optional[str] = None
    queue: Optional[str] = None
    department: Optional[str] = None
    closure_reason: Optional[str] = None
    case_status: Optional[str] = None
    on_time: Optional[str] = None
    sla_target_dt: Optional[str] = None
    closed_dt: Optional[str] = None
    submitted_photo: Optional[str] = None
    closed_photo: Optional[str] = None
    source: Optional[str] = None
    neighborhood: Optional[str] = None
    ward: Optional[str] = None
    precinct: Optional[str] = None
    descriptor: Optional[str] = None
    resolution_description: Optional[str] = None
    resolution_action_updated_date: Optional[str] = None

    owner_name: Optional[str]
    owner_phone: Optional[str]
    owner_email: Optional[str]
    owner_status: Optional[str] = None

    date_reported: datetime
    image_url: Optional[str]
    source_url: Optional[str]


# API Response
class LeadResponse(BaseModel):
    id: str
    external_id: str
    address: str
    city: str
    issue_category: str
    issue_description: str
    owner_name: Optional[str]
    owner_phone: Optional[str]
    owner_email: Optional[str] = None
    date_reported: datetime
    urgency_level: str
    image_url: Optional[str]
    status: str = "new"
    favorited: bool = False

    # Address details
    address_unit: Optional[str] = None
    address_type: Optional[str] = None
    address_street: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_zip: Optional[str] = None

    # Historical details from 311 systems
    case_title: Optional[str] = None
    subject: Optional[str] = None
    reason: Optional[str] = None
    type: Optional[str] = None
    queue: Optional[str] = None
    department: Optional[str] = None
    closure_reason: Optional[str] = None
    case_status: Optional[str] = None
    on_time: Optional[str] = None
    sla_target_dt: Optional[str] = None
    closed_dt: Optional[str] = None
    submitted_photo: Optional[str] = None
    closed_photo: Optional[str] = None
    source: Optional[str] = None
    neighborhood: Optional[str] = None
    ward: Optional[str] = None
    precinct: Optional[str] = None
    descriptor: Optional[str] = None
    resolution_description: Optional[str] = None
    resolution_action_updated_date: Optional[str] = None

    # Owner mailing address
    mailing_address: Optional[str] = None

    # Visibility fields (Phase 4.2)
    visibility_status: Optional[str] = None  # "available" | "reserved_by_me" | "reserved_by_other"
    reserved_by_me: Optional[dict] = None  # {created_at, expires_at, hours_remaining}
    reserved_by_other: Optional[dict] = None  # {contractor_id, contractor_name, expires_at}

    model_config = ConfigDict(exclude_none=False)


class LeadsListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    leads: List[LeadResponse]


class NoteCreate(BaseModel):
    note: str


class NoteResponse(BaseModel):
    id: int
    lead_id: int
    note: str
    created_at: str


class NotificationResponse(BaseModel):
    id: int
    type: str
    title: str
    message: str
    lead_id: Optional[int] = None
    created_at: str
    read: bool


class LeadStatsResponse(BaseModel):
    total: int
    with_owner: int
    reported_today: int
    contacted: int
    favorited: int
    by_category: dict


class LeadUpdate(BaseModel):
    status: Optional[str] = None
    owner_phone: Optional[str] = None


# User
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    company_name: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    company_name: Optional[str] = None
    cities_filter: Optional[List[str]] = None


class UserResponse(BaseModel):
    id: int
    email: str
    company_name: Optional[str] = None
    plan: Optional[str] = None
    subscription_status: Optional[str] = None
    plan_until: Optional[str] = None
    score: int = 0
    leads_taken: int = 0
    conversions: int = 0
    created_at: Optional[str] = None


class AuthResponse(BaseModel):
    token: str
    user: UserResponse


class InterestsUpdate(BaseModel):
    categories: List[str]


class ReserverLeadRequest(BaseModel):
    minutes: int = 15


ALLOWED_RELEASE_REASONS = ["no_answer", "declined", "out_of_area", "personal_emergency", "changed_mind", "lazy", "other"]
SUSPICIOUS_RELEASE_REASONS = ["changed_mind", "lazy"]


class ReleaseLeadRequest(BaseModel):
    reason: Optional[str] = None
    note: Optional[str] = None

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v):
        if v is None:
            return v
        if v not in ALLOWED_RELEASE_REASONS:
            raise ValueError(f"reason deve ser um de: {', '.join(ALLOWED_RELEASE_REASONS)}")
        return v


class ContactLeadRequest(BaseModel):
    channel: str = "sms"


class RejectLeadRequest(BaseModel):
    reason: Optional[str] = None


class LeadStatusResponse(BaseModel):
    id: int
    external_id: str
    address: Optional[str] = None
    city: Optional[str] = None
    issue_category: Optional[str] = None
    lead_status: Optional[str] = None
    reserved_by: Optional[int] = None
    reserved_until: Optional[str] = None
    contact_count: int = 0
    converted_by: Optional[int] = None
    converted_at: Optional[str] = None
    created_at: Optional[str] = None


class LeadHoldResponse(BaseModel):
    reserved: bool
    status: str
    expires_at: Optional[str] = None
    message: Optional[str] = None


class HistoryEvent(BaseModel):
    id: int
    lead_id: int
    event_type: str
    detail: Optional[str] = None
    created_at: str
    user_id: Optional[int] = None
