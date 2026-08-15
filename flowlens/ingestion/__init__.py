"""Input validation and channel-quality assessment.

Everything here runs *before* any diagnosis. If the data cannot support a
conclusion, that has to be established first - otherwise an instrumentation
defect gets reported as an equipment failure.
"""

from flowlens.ingestion.quality import StreamQuality, assess_quality
from flowlens.ingestion.validate import ValidationIssue, validate_run

__all__ = ["StreamQuality", "assess_quality", "ValidationIssue", "validate_run"]
