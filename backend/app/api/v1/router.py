from fastapi import APIRouter

from app.api.v1.alert_rules import router as alert_rules_router
from app.api.v1.alerts import router as alerts_router
from app.api.v1.audit_logs import router as audit_logs_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.traces import router as traces_router
from app.api.v1.workspaces import router as workspaces_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(workspaces_router)
api_v1_router.include_router(organizations_router)
api_v1_router.include_router(documents_router)
api_v1_router.include_router(conversations_router)
api_v1_router.include_router(chat_router)
api_v1_router.include_router(audit_logs_router)
api_v1_router.include_router(traces_router)
api_v1_router.include_router(alerts_router)
api_v1_router.include_router(alert_rules_router)

