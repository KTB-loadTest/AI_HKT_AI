
from __future__ import annotations
import os
import shutil
import uuid
from app.core.config import settings


def ensure_temp_root() -> None:
    os.makedirs(settings.TEMP_DIR, exist_ok=True)


def create_job_dir() -> str:
    """
    요청 1건당 임시 작업 폴더 생성
    """
    ensure_temp_root()
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(settings.TEMP_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    return job_dir


def write_bytes(path: str, data: bytes) -> None:
    """
    bytes를 파일로 저장
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def cleanup_job_dir(job_dir: str) -> None:
    """
    작업 종료 후 임시 폴더 삭제
    """
    if settings.KEEP_TEMP:
        return
    shutil.rmtree(job_dir, ignore_errors=True)
