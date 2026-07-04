"""專案檔案系統儲存層。

無資料庫：所有狀態存於 `<root>/<project_id>/project.json`。
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_SUBDIRS = ("source", "md", "assets", "svg_output", "exports")
_PROJECT_FILE = "project.json"


class ProjectNotFoundError(Exception):
    """指定的專案不存在，或其 project.json 遺失／損毀。"""


@dataclass(frozen=True)
class ProjectSummary:
    id: str
    name: str
    created_at: str
    stage: str


class Project:
    """單一專案的記憶體表示，對應磁碟上的 `<root>/<id>/`。"""

    def __init__(self, root: Path, data: dict):
        self.root = root
        self.data = data

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def path(self) -> Path:
        return self.root / self.id

    def set_slide_status(self, index: int, status: str) -> None:
        """設定第 index 頁的狀態（pending|generated|failed）。

        若該 index 尚無紀錄則自動補建（從 pending、retries=0 起算）。
        status 轉為 "failed" 時 retries 累加 1。
        """
        slides = self.data["slides"]
        while len(slides) <= index:
            slides.append({"status": "pending", "retries": 0})

        slide = slides[index]
        slide["status"] = status
        if status == "failed":
            slide["retries"] = slide.get("retries", 0) + 1

    def save(self) -> None:
        """原子寫入 project.json（tmp 檔 + os.replace）。"""
        project_file = self.path / _PROJECT_FILE
        try:
            tmp_path = self.path / f".{_PROJECT_FILE}.{uuid4().hex}.tmp"
            tmp_path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp_path, project_file)
        except OSError as exc:
            raise OSError(f"寫入專案檔案失敗：{project_file}（{exc}）") from exc


def create_project(root: Path, name: str) -> Project:
    """建立專案目錄骨架與初始 project.json，回傳 Project。"""
    project_id = uuid4().hex[:8]
    project_root = root / project_id
    for sub in _SUBDIRS:
        (project_root / sub).mkdir(parents=True, exist_ok=True)

    data = {
        "id": project_id,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stage": "ingest",
        "mode": "A",
        "style_id": None,
        "palette_id": None,
        "spec_locked": False,
        "slides": [],
    }
    project = Project(root, data)
    project.save()
    return project


def load_project(root: Path, project_id: str) -> Project:
    """從磁碟載入專案；不存在或損毀則拋出 ProjectNotFoundError。"""
    project_file = root / project_id / _PROJECT_FILE
    try:
        raw = project_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectNotFoundError(f"找不到專案：{project_id}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectNotFoundError(f"專案檔案損毀：{project_id}") from exc

    return Project(root, data)


def list_projects(root: Path) -> list[ProjectSummary]:
    """列出 root 下所有專案摘要，依 created_at 排序；略過壞損目錄。"""
    if not root.is_dir():
        return []

    summaries: list[ProjectSummary] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        try:
            project = load_project(root, entry.name)
        except ProjectNotFoundError:
            continue
        summaries.append(
            ProjectSummary(
                id=project.data["id"],
                name=project.data["name"],
                created_at=project.data["created_at"],
                stage=project.data["stage"],
            )
        )

    summaries.sort(key=lambda s: s.created_at)
    return summaries
