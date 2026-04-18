"""
Audit logging for admin operations.
Structured logging for security and compliance.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """Actions auditées."""
    DOCUMENT_CREATE = "document.create"
    DOCUMENT_READ = "document.read"
    DOCUMENT_UPDATE = "document.update"
    DOCUMENT_DELETE = "document.delete"
    DOCUMENT_INGEST = "document.ingest"
    DOCUMENT_LIST = "document.list"
    INGESTION_LIST = "ingestion.list"
    INGESTION_CREATE = "ingestion.create"
    INGESTION_COMPLETE = "ingestion.complete"
    UPLOAD_CREATE = "upload.create"
    REINDEX_TRIGGER = "reindex.trigger"
    ADMIN_LOGIN = "admin.login"
    ADMIN_LOGOUT = "admin.logout"
    SECURITY_VIOLATION = "security.violation"


class AuditStatus(str, Enum):
    """Statut de l'action auditée."""
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    ERROR = "error"


@dataclass
class AuditEvent:
    """Événement d'audit structuré."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    action: str = ""
    status: str = ""
    user_id: str | None = None
    client_ip: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation."""
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "status": self.status,
            "user_id": self.user_id,
            "client_ip": self.client_ip,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "request_id": self.request_id,
        }

    def to_json(self) -> str:
        """Sérialise en JSON."""
        return json.dumps(self.to_dict(), separators=(",", ":"))


class AuditLogger:
    """Logger d'audit pour les opérations admin."""

    def __init__(
        self,
        log_file: str | None = None,
        log_level: int = logging.INFO,
        include_console: bool = True,
    ):
        """
        Initialise le logger d'audit.

        Args:
            log_file: Chemin vers le fichier de log (optionnel).
            log_level: Niveau de log.
            include_console: Inclure la sortie console.
        """
        self.logger = logging.getLogger("rag.audit")
        self.logger.setLevel(log_level)
        self.logger.handlers = []  # Reset handlers

        # Formatter JSON
        self.formatter = logging.Formatter("%(message)s")

        # Handler fichier
        if log_file:
            try:
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
                file_handler = logging.FileHandler(log_file, encoding="utf-8")
                file_handler.setLevel(log_level)
                file_handler.setFormatter(self.formatter)
                self.logger.addHandler(file_handler)
            except OSError as e:
                logger.warning("Cannot create audit log file '%s': %s", log_file, e)

        # Handler console
        if include_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(log_level)
            console_handler.setFormatter(self.formatter)
            self.logger.addHandler(console_handler)

    def log(
        self,
        action: AuditAction | str,
        status: AuditStatus | str,
        client_ip: str | None = None,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        """
        Enregistre un événement d'audit.

        Args:
            action: Action effectuée.
            status: Statut de l'action.
            client_ip: IP du client.
            user_id: Identifiant utilisateur (si authentifié).
            resource_type: Type de ressource (document, ingestion, etc.).
            resource_id: ID de la ressource.
            details: Détails supplémentaires.
            request_id: ID de la requête pour le tracing.
        """
        event = AuditEvent(
            action=str(action),
            status=str(status),
            client_ip=client_ip,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            request_id=request_id,
        )

        log_method = self.logger.info
        if status in (AuditStatus.FAILURE, AuditStatus.DENIED, AuditStatus.ERROR):
            log_method = self.logger.warning

        log_method(event.to_json())

    def log_success(
        self,
        action: AuditAction | str,
        client_ip: str | None = None,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Log un succès."""
        self.log(
            action=action,
            status=AuditStatus.SUCCESS,
            client_ip=client_ip,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            **kwargs,
        )

    def log_failure(
        self,
        action: AuditAction | str,
        reason: str,
        client_ip: str | None = None,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Log un échec."""
        detail_dict = details.copy() if details else {}
        detail_dict["failure_reason"] = reason
        self.log(
            action=action,
            status=AuditStatus.FAILURE,
            client_ip=client_ip,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=detail_dict,
            **kwargs,
        )

    def log_denied(
        self,
        action: AuditAction | str,
        reason: str,
        client_ip: str,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Log un accès refusé."""
        self.log(
            action=action,
            status=AuditStatus.DENIED,
            client_ip=client_ip,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details={"denial_reason": reason},
            **kwargs,
        )

    def log_security_violation(
        self,
        violation_type: str,
        client_ip: str,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Log une violation de sécurité."""
        detail_dict = details.copy() if details else {}
        detail_dict["violation_type"] = violation_type
        self.log(
            action=AuditAction.SECURITY_VIOLATION,
            status=AuditStatus.DENIED,
            client_ip=client_ip,
            resource_type="security",
            details=detail_dict,
            **kwargs,
        )


# Instance globale (lazy initialization)
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Obtient l'instance du logger d'audit."""
    global _audit_logger
    if _audit_logger is None:
        log_file = os.getenv("AUDIT_LOG_FILE")
        _audit_logger = AuditLogger(
            log_file=log_file,
            log_level=logging.INFO,
            include_console=True,
        )
    return _audit_logger


def log_admin_action(
    action: AuditAction,
    status: AuditStatus,
    request: Any,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Helper pour logger une action admin.

    Args:
        action: Action effectuée.
        status: Statut.
        request: Objet requête FastAPI.
        resource_type: Type de ressource.
        resource_id: ID de ressource.
        details: Détails supplémentaires.
    """
    audit = get_audit_logger()
    client_ip = _get_client_ip(request)
    request_id = _get_request_id(request)

    audit.log(
        action=action,
        status=status,
        client_ip=client_ip,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        request_id=request_id,
    )


def _get_client_ip(request: Any) -> str:
    """Extrait l'IP client de la requête."""
    headers = getattr(request, "headers", {}) or {}
    forwarded = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
    if isinstance(forwarded, str) and forwarded.strip():
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return host or "unknown"


def _get_request_id(request: Any) -> str | None:
    """Extrait l'ID de requête pour le tracing."""
    headers = getattr(request, "headers", {}) or {}
    return headers.get("X-Request-ID") or headers.get("x-request-id")
