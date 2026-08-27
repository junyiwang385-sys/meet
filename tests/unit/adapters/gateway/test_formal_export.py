import json
import unittest

from meeting_agent.adapters.gateway.formal_export import (
    build_formal_exports,
    render_formal_html,
    render_formal_json,
    render_formal_txt,
)


def _content():
    return {
        "title": "接口鉴权评审",
        "speaker_names": {"speaker_0": "张三", "speaker_1": "李四"},
        "transcript_edits": [],
        "minutes": {"overview": "会议确定统一走网关校验令牌再回源。", "outline": []},
        "chapters": [
            {"title": "鉴权方案", "summary": "统一网关校验。", "start_ms": 0, "end_ms": 65000},
        ],
        "decisions": [{"decision_id": "d1", "text": "采用网关统一鉴权。"}],
        "action_items": [
            {"action_id": "a1", "text": "补充令牌刷新逻辑", "owner": "speaker_0", "due_date": "2026-09-01"},
            {"action_id": "a2", "text": "无owner的待办", "owner": None, "due_date": None},
        ],
        "review_marks": {},
    }


class FormalExportTests(unittest.TestCase):
    def test_txt_contains_sections_and_owner_label(self):
        txt = render_formal_txt(_content())
        self.assertIn("会议纪要：接口鉴权评审", txt)
        self.assertIn("统一走网关校验", txt)
        self.assertIn("[0m00s-1m05s] 鉴权方案", txt)
        self.assertIn("负责人：张三", txt)      # owner 用 speaker_names 映射
        self.assertIn("负责人：未指定", txt)     # 无 owner 兜底

    def test_json_shape(self):
        data = render_formal_json(_content(), meeting_id="m1", revision=3, finalized_at="2026-08-27T00:00:00Z")
        self.assertEqual(data["schema_version"], "formal-minutes.v1")
        self.assertEqual(data["meeting_id"], "m1")
        self.assertEqual(data["revision"], 3)
        self.assertEqual(data["title"], "接口鉴权评审")
        self.assertEqual(len(data["chapters"]), 1)
        self.assertEqual(data["decisions"], ["采用网关统一鉴权。"])
        self.assertEqual(data["action_items"][0]["owner"], "张三")

    def test_html_escapes_and_structs(self):
        content = _content()
        content["title"] = "<script>x</script>"
        htmltext = render_formal_html(content, meeting_id="m1", finalized_at="t")
        self.assertIn("<!doctype html>", htmltext)
        self.assertNotIn("<script>x</script>", htmltext)   # 转义
        self.assertIn("&lt;script&gt;", htmltext)
        self.assertIn("鉴权方案", htmltext)

    def test_build_exports_bundle_and_manifest(self):
        bundle = build_formal_exports(
            _content(), meeting_id="m1", revision=2, finalized_at="t", formats=["html", "txt", "json"],
        )
        files = bundle["files"]
        self.assertIn("formal_minutes.html", files)
        self.assertIn("formal_minutes.txt", files)
        self.assertIn("formal_result.json", files)
        self.assertIn("manifest.json", files)
        # json 文件可解析
        json.loads(files["formal_result.json"]["text"])
        manifest = json.loads(files["manifest.json"]["text"])
        self.assertEqual(manifest["schema_version"], "formal-manifest.v1")
        self.assertEqual(set(manifest["formats"]), {"html", "txt", "json"})

    def test_subset_formats(self):
        bundle = build_formal_exports(_content(), meeting_id="m", revision=1, finalized_at="t", formats=["txt"])
        self.assertIn("formal_minutes.txt", bundle["files"])
        self.assertNotIn("formal_minutes.html", bundle["files"])
        self.assertIn("manifest.json", bundle["files"])

    def test_empty_formats_defaults_to_all(self):
        bundle = build_formal_exports(_content(), meeting_id="m", revision=1, finalized_at="t", formats=[])
        self.assertEqual(set(bundle["formats"]), {"html", "txt", "json"})

    def test_missing_minutes_is_safe(self):
        content = _content()
        content["minutes"] = None
        content["chapters"] = []
        txt = render_formal_txt(content)
        self.assertIn("全文摘要", txt)
        self.assertIn("无", txt)


if __name__ == "__main__":
    unittest.main()
