# Import all models to guarantee SQLAlchemy registers them with the shared
# metadata before the mapper is configured. This prevents relationship
# resolution errors at startup ("Mapper could not assemble any primary key").
from app.models.company import Company  # noqa: F401
from app.models.analysis import Analysis, AnalysisStatus  # noqa: F401
from app.models.source import Source, SourceType, SourceStatus  # noqa: F401
from app.models.finding import Finding, EvidenceType, ConfidenceLevel  # noqa: F401
from app.models.llm_result import LLMResult  # noqa: F401
from app.models.report import Report, PriorityRating  # noqa: F401
