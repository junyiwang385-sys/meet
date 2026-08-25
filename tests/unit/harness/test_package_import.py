import unittest

from meeting_agent.harness import HARNESS_VERSION, RESULT_SCHEMA_VERSION
from meeting_agent.harness.pipeline import PipelineStageError
from meeting_agent.stages.product_summary import ProductSummaryConfig


class ExtractedPackageImportTests(unittest.TestCase):
    def test_core_package_exports_current_versions(self):
        self.assertEqual(HARNESS_VERSION, "2.0.0")
        self.assertEqual(RESULT_SCHEMA_VERSION, "meeting-result.v2")
        self.assertEqual(ProductSummaryConfig.__name__, "ProductSummaryConfig")

    def test_pipeline_error_keeps_return_code_contract(self):
        error = PipelineStageError("llm_summary", "validation_failed", "截断", 7)
        self.assertEqual(error.as_dict()["return_code"], 7)


if __name__ == "__main__":
    unittest.main()
