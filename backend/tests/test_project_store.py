import pytest

from app.store.project import (
    ProjectNotFoundError,
    ProjectSummary,
    create_project,
    list_projects,
    load_project,
)


def test_create_and_reload(tmp_path):
    p = create_project(tmp_path, "月報")
    assert (tmp_path / p.id / "source").is_dir()
    assert (tmp_path / p.id / "svg_output").is_dir()
    p.set_slide_status(0, "generated")
    p.save()
    p2 = load_project(tmp_path, p.id)
    assert p2.data["slides"][0]["status"] == "generated"
    assert p2.data["stage"] == "ingest"


def test_slide_retry_counter(tmp_path):
    p = create_project(tmp_path, "x")
    p.set_slide_status(0, "failed")
    p.set_slide_status(0, "failed")
    assert p.data["slides"][0]["retries"] == 2


def test_create_project_directory_skeleton(tmp_path):
    p = create_project(tmp_path, "skeleton")
    root = tmp_path / p.id
    for sub in ("source", "md", "assets", "svg_output", "exports"):
        assert (root / sub).is_dir(), f"missing {sub}"
    assert (root / "project.json").is_file()


def test_create_project_initial_fields(tmp_path):
    p = create_project(tmp_path, "初始欄位")
    assert p.data["name"] == "初始欄位"
    assert p.data["stage"] == "ingest"
    assert p.data["mode"] == "A"
    assert p.data["style_id"] is None
    assert p.data["palette_id"] is None
    assert p.data["spec_locked"] is False
    assert p.data["slides"] == []
    assert len(p.id) == 8
    assert "created_at" in p.data


def test_set_slide_status_creates_missing_index_as_pending_first(tmp_path):
    p = create_project(tmp_path, "y")
    p.set_slide_status(2, "generated")
    slides = p.data["slides"]
    assert len(slides) == 3
    assert slides[0]["status"] == "pending"
    assert slides[1]["status"] == "pending"
    assert slides[2]["status"] == "generated"
    assert slides[0]["retries"] == 0


def test_slides_have_index_field(tmp_path):
    p = create_project(tmp_path, "idx")
    p.set_slide_status(2, "generated")
    assert [s["index"] for s in p.data["slides"]] == [0, 1, 2]
    # 更新既有項目時 index 不變
    p.set_slide_status(1, "failed")
    assert p.data["slides"][1]["index"] == 1


def test_set_slide_status_negative_index_raises(tmp_path):
    p = create_project(tmp_path, "neg")
    with pytest.raises(ValueError, match="-1"):
        p.set_slide_status(-1, "generated")
    assert p.data["slides"] == []


def test_set_slide_status_invalid_status_raises(tmp_path):
    p = create_project(tmp_path, "bad")
    with pytest.raises(ValueError, match="oops"):
        p.set_slide_status(0, "oops")
    assert p.data["slides"] == []


def test_set_slide_status_non_failed_does_not_increment_retries(tmp_path):
    p = create_project(tmp_path, "z")
    p.set_slide_status(0, "failed")
    p.set_slide_status(0, "generated")
    assert p.data["slides"][0]["status"] == "generated"
    assert p.data["slides"][0]["retries"] == 1


def test_load_nonexistent_project_raises(tmp_path):
    with pytest.raises(ProjectNotFoundError):
        load_project(tmp_path, "doesnotexist")


def test_list_projects_sorted_and_skips_broken_dirs(tmp_path):
    p1 = create_project(tmp_path, "第一個")
    p1.save()
    p2 = create_project(tmp_path, "第二個")
    p2.save()

    # broken directory: no project.json inside
    broken = tmp_path / "broken_dir"
    broken.mkdir()

    summaries = list_projects(tmp_path)
    assert all(isinstance(s, ProjectSummary) for s in summaries)
    ids = [s.id for s in summaries]
    assert p1.id in ids
    assert p2.id in ids
    assert "broken_dir" not in ids
    # sorted by created_at ascending
    created_ats = [s.created_at for s in summaries]
    assert created_ats == sorted(created_ats)


def test_list_projects_empty_root(tmp_path):
    assert list_projects(tmp_path) == []


def test_save_is_atomic_no_leftover_tmp_file(tmp_path):
    p = create_project(tmp_path, "atomic")
    p.save()
    root = tmp_path / p.id
    leftover = list(root.glob("*.tmp"))
    assert leftover == []
