"""Register all tables and preserve existing `from app.models import Incident` imports."""

from app.models.governance import AuditEvent as AuditEvent
from app.models.governance import Feedback as Feedback
from app.models.incident import Environment as Environment
from app.models.incident import Incident as Incident
from app.models.incident import IncidentStatus as IncidentStatus
from app.models.processing import AnalysisJob as AnalysisJob
from app.models.processing import IncidentAnalysis as IncidentAnalysis
from app.models.processing import LogEvent as LogEvent
from app.models.processing import LogFile as LogFile
from app.models.processing import StorageDeletion as StorageDeletion
from app.models.users import RefreshToken as RefreshToken
from app.models.users import User as User
from app.models.users import UserRole as UserRole
