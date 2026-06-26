"""Tests for Workspace ops (Docs/Sheets/Slides) and Drive delete.

Each op takes an authenticated googleapiclient service. We mock the service
and assert the right API request is issued (the batchUpdate request shapes are
the fiddly part) and that read output is truncated.
"""

from unittest.mock import MagicMock

from integrations.google import docs_ops, sheets_ops, slides_ops, drive_ops


# ── Docs ─────────────────────────────────────────────────────────────────────

class TestDocsOps:
    def test_get_document_extracts_text_and_truncates(self):
        service = MagicMock()
        service.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "DOC1", "title": "My Doc",
            "body": {"content": [
                {"paragraph": {"elements": [
                    {"textRun": {"content": "Hello "}},
                    {"textRun": {"content": "world"}},
                ]}},
            ]},
        }
        out = docs_ops.get_document_op(service, "DOC1", max_chars=8)
        assert out["title"] == "My Doc"
        assert out["content"] == "Hello wo"
        assert out["truncated"] is True
        assert out["char_count"] == 11
        assert out["web_link"].endswith("/DOC1/edit")

    def test_create_document_seeds_initial_content(self):
        service = MagicMock()
        service.documents.return_value.create.return_value.execute.return_value = {
            "documentId": "NEW", "title": "T",
        }
        out = docs_ops.create_document_op(service, "T", content="seed")
        _, kwargs = service.documents.return_value.batchUpdate.call_args
        req = kwargs["body"]["requests"][0]["insertText"]
        assert req["location"]["index"] == 1
        assert req["text"] == "seed"
        assert out["document_id"] == "NEW"

    def test_create_document_no_content_skips_batch_update(self):
        service = MagicMock()
        service.documents.return_value.create.return_value.execute.return_value = {"documentId": "NEW", "title": "T"}
        docs_ops.create_document_op(service, "T")
        service.documents.return_value.batchUpdate.assert_not_called()

    def test_append_text_inserts_before_trailing_newline(self):
        service = MagicMock()
        service.documents.return_value.get.return_value.execute.return_value = {
            "body": {"content": [{"endIndex": 12}]}
        }
        out = docs_ops.append_text_op(service, "DOC1", "more")
        _, kwargs = service.documents.return_value.batchUpdate.call_args
        req = kwargs["body"]["requests"][0]["insertText"]
        assert req["location"]["index"] == 11  # endIndex - 1
        assert req["text"] == "\nmore"
        assert out["inserted_at"] == 11

    def test_replace_text_builds_replace_all_request(self):
        service = MagicMock()
        service.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"replaceAllText": {"occurrencesChanged": 3}}]
        }
        out = docs_ops.replace_text_op(service, "DOC1", "foo", "bar", match_case=True)
        _, kwargs = service.documents.return_value.batchUpdate.call_args
        req = kwargs["body"]["requests"][0]["replaceAllText"]
        assert req["containsText"] == {"text": "foo", "matchCase": True}
        assert req["replaceText"] == "bar"
        assert out["occurrences_changed"] == 3


# ── Sheets ───────────────────────────────────────────────────────────────────

class TestSheetsOps:
    def test_get_values_truncates_large_range(self, monkeypatch):
        monkeypatch.setattr(sheets_ops, "_MAX_READ_CELLS", 3)
        service = MagicMock()
        service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "range": "S!A1:B3", "values": [["a", "b"], ["c", "d"], ["e", "f"]],
        }
        out = sheets_ops.get_values_op(service, "SS", "S!A1:B3")
        assert out["truncated"] is True
        assert out["row_count"] == 1  # first 2-cell row kept; next would exceed cap

    def test_update_values_uses_user_entered(self):
        service = MagicMock()
        service.spreadsheets.return_value.values.return_value.update.return_value.execute.return_value = {
            "updatedRange": "S!A1:B1", "updatedCells": 2,
        }
        out = sheets_ops.update_values_op(service, "SS", "S!A1", [["1", "2"]])
        _, kwargs = service.spreadsheets.return_value.values.return_value.update.call_args
        assert kwargs["valueInputOption"] == "USER_ENTERED"
        assert kwargs["body"] == {"values": [["1", "2"]]}
        assert out["updated_cells"] == 2

    def test_append_rows_inserts_rows(self):
        service = MagicMock()
        service.spreadsheets.return_value.values.return_value.append.return_value.execute.return_value = {
            "updates": {"updatedRange": "S!A2:C2", "updatedRows": 1},
        }
        out = sheets_ops.append_rows_op(service, "SS", "S!A:C", [["x", "y", "z"]])
        _, kwargs = service.spreadsheets.return_value.values.return_value.append.call_args
        assert kwargs["insertDataOption"] == "INSERT_ROWS"
        assert out["updated_rows"] == 1

    def test_add_sheet_returns_new_tab(self):
        service = MagicMock()
        service.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"addSheet": {"properties": {"sheetId": 5, "title": "Q3"}}}]
        }
        out = sheets_ops.add_sheet_op(service, "SS", "Q3")
        _, kwargs = service.spreadsheets.return_value.batchUpdate.call_args
        assert kwargs["body"]["requests"][0]["addSheet"]["properties"]["title"] == "Q3"
        assert out["sheet_id"] == 5


# ── Slides ───────────────────────────────────────────────────────────────────

class TestSlidesOps:
    def test_get_presentation_extracts_per_slide_text(self):
        service = MagicMock()
        service.presentations.return_value.get.return_value.execute.return_value = {
            "presentationId": "P1", "title": "Deck",
            "slides": [
                {"objectId": "s1", "pageElements": [
                    {"shape": {"text": {"textElements": [{"textRun": {"content": "Title"}}]}}}
                ]},
            ],
        }
        out = slides_ops.get_presentation_op(service, "P1")
        assert out["title"] == "Deck"
        assert out["slides"][0] == {"slide_object_id": "s1", "text": "Title"}

    def test_get_presentation_extracts_table_cell_text(self):
        service = MagicMock()
        service.presentations.return_value.get.return_value.execute.return_value = {
            "presentationId": "P1", "title": "Deck",
            "slides": [
                {"objectId": "s1", "pageElements": [
                    {"table": {"tableRows": [
                        {"tableCells": [
                            {"text": {"textElements": [{"textRun": {"content": "Cell"}}]}},
                        ]},
                    ]}},
                ]},
            ],
        }
        out = slides_ops.get_presentation_op(service, "P1")
        assert out["slides"][0]["text"] == "Cell"

    def test_add_slide_creates_slide_with_layout(self):
        service = MagicMock()
        service.presentations.return_value.batchUpdate.return_value.execute.return_value = {}
        out = slides_ops.add_slide_op(service, "P1", layout="TITLE")
        _, kwargs = service.presentations.return_value.batchUpdate.call_args
        req = kwargs["body"]["requests"][0]["createSlide"]
        assert req["slideLayoutReference"]["predefinedLayout"] == "TITLE"
        assert out["slide_object_id"] == req["objectId"]

    def test_insert_text_creates_textbox_then_inserts(self):
        service = MagicMock()
        service.presentations.return_value.batchUpdate.return_value.execute.return_value = {}
        out = slides_ops.insert_text_op(service, "P1", "slide1", "Hi")
        _, kwargs = service.presentations.return_value.batchUpdate.call_args
        reqs = kwargs["body"]["requests"]
        assert reqs[0]["createShape"]["shapeType"] == "TEXT_BOX"
        assert reqs[0]["createShape"]["elementProperties"]["pageObjectId"] == "slide1"
        assert reqs[1]["insertText"]["text"] == "Hi"
        # the two requests reference the same new shape objectId
        assert reqs[0]["createShape"]["objectId"] == reqs[1]["insertText"]["objectId"]
        assert out["text_box_object_id"] == reqs[0]["createShape"]["objectId"]

    def test_replace_all_text_counts_occurrences(self):
        service = MagicMock()
        service.presentations.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"replaceAllText": {"occurrencesChanged": 2}}]
        }
        out = slides_ops.replace_all_text_op(service, "P1", "{{name}}", "Ada")
        assert out["occurrences_changed"] == 2


# ── Drive delete ─────────────────────────────────────────────────────────────

class TestDriveDelete:
    def test_delete_trashes_by_default(self):
        service = MagicMock()
        service.files.return_value.update.return_value.execute.return_value = {
            "id": "F", "name": "doc", "trashed": True,
        }
        out = drive_ops.delete_file_op(service, "F")
        _, kwargs = service.files.return_value.update.call_args
        assert kwargs["body"] == {"trashed": True}
        assert out["trashed"] is True
        service.files.return_value.delete.assert_not_called()

    def test_delete_permanent_hard_deletes(self):
        service = MagicMock()
        out = drive_ops.delete_file_op(service, "F", permanent=True)
        service.files.return_value.delete.assert_called_once_with(fileId="F")
        assert out["permanently_deleted"] is True
