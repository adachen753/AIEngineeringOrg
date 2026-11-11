import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_manager import cli
from ai_manager.submission_file import MAX_FILE_BYTES, load_submission_file, parse_submission_file


@pytest.fixture
def body():
    return {
        "repo": "C:/example/repo", "base_commit": "a" * 40, "feature": "Implement 中文 feature",
        "allowed_paths": ["src/main.py"], "test_paths": ["tests/test_main.py"],
        "acceptance": ["Tests pass"], "idempotency_key": "file-test", "authorized": True,
    }


def encode(body):
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def markdown(body, fence="~~~"):
    return b"Description: do not execute this prose.\n" + fence.encode() + b"json\n" + encode(body) + b"\n" + fence.encode() + b"\nMore description."


@pytest.mark.parametrize("suffix", [".json", ".md", ".JSON"])
def test_file_round_trip_and_explicit_authorization(tmp_path, body, suffix):
    path = tmp_path / ("submission" + suffix)
    path.write_bytes(markdown(body) if suffix == ".md" else encode(body))
    parsed = load_submission_file(path)
    assert parsed.submission.authorized is True
    assert parsed.payload()["authorized"] is False
    assert parsed.payload(approved=True)["authorized"] is True
    assert parsed.payload()["feature"] == body["feature"]
    assert "Description" in parsed.description if suffix == ".md" else parsed.description == ""
    assert "description" not in parsed.payload()


@pytest.mark.parametrize("fence", ["~~~", "\x60\x60\x60", "~~~~"])
def test_markdown_fences(body, fence):
    assert parse_submission_file(markdown(body, fence), "file.md").submission.feature == body["feature"]


@pytest.mark.parametrize("content", [
    b"{}", b"~~~json\n{}", b"~~~python\n{}\n~~~", b"~~~json\n{}\n~~~\n~~~json\n{}\n~~~",
    b"~~~json\n{}\n\x60\x60\x60", b"~~~json\n{}\n~~~\n~~~python\npass\n~~~",
])
def test_invalid_markdown(content):
    with pytest.raises(ValueError, match="exactly one fenced json"):
        parse_submission_file(content, "file.md")


@pytest.mark.parametrize("content", [b"\xff", b"{} trailing", b"[]", b'{"repo":"one","repo":"two"}',
                                         b'{"feature":NaN}', b'{"feature":Infinity}', rb'{"feature":"\ud800"}'])
def test_invalid_json_and_unicode(content):
    with pytest.raises(ValueError):
        parse_submission_file(content, "file.json")


@pytest.mark.parametrize("field,value", [
    ("unexpected", True), ("authorized", "true"), ("timeout_seconds", "300"),
    ("timeout_seconds", True), ("allowed_paths", "src"), ("allowed_paths", ["../src"]),
    ("test_command", ["echo", "unsafe"]), ("base_commit", "short"),
    ("acceptance", []), ("acceptance", ["ok"] * 101), ("allowed_paths", ["a" * 1025]),
    ("repo", "a" * 1025), ("feature", "a" * 12001), ("acceptance", ["a" * 12001]),
])
def test_strict_shape_and_limits(body, field, value):
    body[field] = value
    with pytest.raises(ValueError):
        parse_submission_file(encode(body), "file.json")


def test_size_bom_and_extension(body):
    data = encode(body)
    assert parse_submission_file(b"\xef\xbb\xbf" + data, "file.json").submission.feature == body["feature"]
    assert parse_submission_file(data + b" " * (MAX_FILE_BYTES - len(data)), "file.json")
    with pytest.raises(ValueError, match="exceeds"):
        parse_submission_file(data + b" " * MAX_FILE_BYTES, "file.json")
    with pytest.raises(ValueError, match=".json or .md"):
        parse_submission_file(data, "file.txt")


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("suffix", [".json", ".md"])
def test_cli_submit(tmp_path, body, monkeypatch, capsys, approved, suffix):
    path = tmp_path / ("file" + suffix)
    path.write_bytes(markdown(body) if suffix == ".md" else encode(body))
    request = MagicMock(return_value={"id": "task"})
    monkeypatch.setattr(cli, "api_request", request)
    assert cli.main(["submit", str(path), *(["--approved"] if approved else [])]) == 0
    assert request.call_args.args[1] == "/workflows"
    assert request.call_args.args[2]["authorized"] is approved
    assert "description" not in request.call_args.args[2]
    assert json.loads(capsys.readouterr().out)["id"] == "task"


def test_cli_invalid_file_never_calls_api(tmp_path, monkeypatch, capsys):
    path = tmp_path / "bad.json"
    path.write_bytes(b"invalid")
    request = MagicMock()
    monkeypatch.setattr(cli, "api_request", request)
    assert cli.main(["submit", str(path)]) == 1
    request.assert_not_called()
    assert capsys.readouterr().err


def test_load_is_bounded(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * (MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds"):
        load_submission_file(path)


def test_deeply_nested_json_is_rejected():
    with pytest.raises(ValueError):
        parse_submission_file(b"[" * 2000 + b"0" + b"]" * 2000, "file.json")


def test_ui_invalid_upload_does_not_submit(monkeypatch):
    from ai_manager import ui
    streamlit = MagicMock()
    streamlit.file_uploader.return_value.name = "bad.json"
    streamlit.file_uploader.return_value.getvalue.return_value = b"invalid"
    streamlit.form_submit_button.return_value = False
    streamlit.button.return_value = False
    streamlit.text_input.return_value = ""
    request = MagicMock(return_value=[])
    monkeypatch.setattr(ui, "st", streamlit)
    monkeypatch.setattr(ui, "api_request", request)
    ui.main()
    streamlit.error.assert_called_once()
    assert len(request.call_args_list) == 1
    assert request.call_args.args[1:] == ("/workflows", None)


@pytest.mark.parametrize("approved", [False, True])
def test_ui_upload_preview_and_authorization(body, monkeypatch, approved):
    from ai_manager import ui
    streamlit = MagicMock()
    streamlit.file_uploader.return_value.name = "file.md"
    streamlit.file_uploader.return_value.getvalue.return_value = markdown(body)
    streamlit.form_submit_button.return_value = False
    streamlit.button.side_effect = lambda label, **kwargs: label == "提交上传文件"
    streamlit.checkbox.return_value = approved
    streamlit.sidebar.text_input.return_value = "http://unit-test.invalid"
    streamlit.text_input.side_effect = lambda label, *args, **kwargs: "" if label.startswith("Workflow ID") else "value"
    request = MagicMock(side_effect=[{"id": "task"}, []])
    monkeypatch.setattr(ui, "st", streamlit)
    monkeypatch.setattr(ui, "api_request", request)
    ui.main()
    assert request.call_args_list[0].args[2]["authorized"] is approved
    assert streamlit.json.call_args.args[0]["authorized"] is False
    streamlit.text.assert_called_once()
    assert streamlit.checkbox.call_args_list[0].kwargs["value"] is False
    assert streamlit.checkbox.call_args_list[0].kwargs["key"].startswith("file_approval_")


def test_templates_are_valid_and_not_authorized():
    root = Path(__file__).resolve().parents[1]
    for name in ("submission.json", "submission.md"):
        assert load_submission_file(root / "templates" / name).payload()["authorized"] is False


@pytest.mark.parametrize("suffix", [".json", ".md"])
def test_parser_accepts_text_for_adapter(body, suffix):
    data = markdown(body) if suffix == ".md" else encode(body)
    assert parse_submission_file(data.decode("utf-8"), "file" + suffix).payload() == parse_submission_file(data, "file" + suffix).payload()


def test_parser_rejects_invalid_text_and_type():
    with pytest.raises(ValueError, match="UTF-8"):
        parse_submission_file("\ud800", "file.json")
    with pytest.raises(ValueError, match="bytes or text"):
        parse_submission_file(None, "file.json")
    with pytest.raises(ValueError, match="exceeds"):
        parse_submission_file("é" * MAX_FILE_BYTES, "file.json")


def test_streamlit_apptest_render_smoke(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from ai_manager import ui
    request = MagicMock(return_value=[])
    monkeypatch.setattr(cli, "api_request", request)
    app = AppTest.from_file(str(Path(ui.__file__).resolve())).run(timeout=10)
    assert not app.exception
    assert len(app.get("file_uploader")) == 1
    assert any(widget.label == "提交" for widget in app.button)
    request.assert_called_once_with("http://127.0.0.1:8765", "/workflows", None)
