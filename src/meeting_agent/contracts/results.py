"""Version constants and stable result contract identifiers."""

# These values are intentionally independent: observability sidecars can evolve
# without forcing a business-result schema migration.
HARNESS_VERSION = "2.0.0"
RESULT_SCHEMA_VERSION = "meeting-result.v2"
SUMMARY_SCHEMA_VERSION = "meeting-summary.v1"
RUN_MANIFEST_SCHEMA_VERSION = "run-manifest.v1"
RUN_EVENT_SCHEMA_VERSION = "run-event.v1"
RUN_METRICS_SCHEMA_VERSION = "run-metrics.v1"
ERROR_REPORT_SCHEMA_VERSION = "error-report.v1"
DIAGNOSTICS_SCHEMA_VERSION = "meeting-diagnostics.v1"

__all__ = [
    "HARNESS_VERSION",
    "RESULT_SCHEMA_VERSION",
    "SUMMARY_SCHEMA_VERSION",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "RUN_EVENT_SCHEMA_VERSION",
    "RUN_METRICS_SCHEMA_VERSION",
    "ERROR_REPORT_SCHEMA_VERSION",
    "DIAGNOSTICS_SCHEMA_VERSION",
]
