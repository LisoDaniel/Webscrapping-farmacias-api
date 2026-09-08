"""Fila em memória para varreduras disparadas pela API.

É apropriada para uma única instância do serviço. A interface deixa a futura
migração para Celery/RQ isolada do restante da API.
"""

from datetime import datetime
from threading import Lock
from typing import Optional
from uuid import uuid4

from app.models.client import ScrapeJobResponse


class ScrapeJobService:
    def __init__(self) -> None:
        self._jobs: dict[str, ScrapeJobResponse] = {}
        self._lock = Lock()

    def create(self, client_folder: str) -> ScrapeJobResponse:
        job = ScrapeJobResponse(
            job_id=uuid4().hex, status="queued", client_folder=client_folder,
            created_at=datetime.now().isoformat(),
        )
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Optional[ScrapeJobResponse]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **values) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for field, value in values.items():
                setattr(job, field, value)
