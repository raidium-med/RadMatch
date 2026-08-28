"""I/O helpers — covers behaviors the orchestrators rely on."""

from __future__ import annotations

from radmatch import io


def test_load_indications_missing_dir_returns_empty(tmp_path):
    assert io.load_indications(None) == {}
    assert io.load_indications(tmp_path / "nope") == {}


def test_load_indications_reads_txt_files(tmp_path):
    (tmp_path / "a.txt").write_text("Trauma — r/o pneumothorax", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Follow-up hepatic mass", encoding="utf-8")
    (tmp_path / "c.json").write_text("{}", encoding="utf-8")  # ignored — wrong ext
    loaded = io.load_indications(tmp_path)
    assert loaded == {"a": "Trauma — r/o pneumothorax", "b": "Follow-up hepatic mass"}


def test_load_indications_empty_file_maps_to_empty_string(tmp_path):
    (tmp_path / "a.txt").write_text("", encoding="utf-8")
    assert io.load_indications(tmp_path) == {"a": ""}
