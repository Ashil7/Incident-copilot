"""Server-rendered browser page shells for the existing JSON API."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")


def page(request, template, **context):
    return templates.TemplateResponse(request=request, name=template, context=context)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return page(request, "app.html", page="dashboard", title="Dashboard")


@router.get("/login", response_class=HTMLResponse)
def login(request: Request):
    return page(request, "auth.html", page="login", title="Sign in")


@router.get("/register", response_class=HTMLResponse)
def register(request: Request):
    return page(request, "auth.html", page="register", title="Create account")


@router.get("/incidents/new", response_class=HTMLResponse)
def new_incident(request: Request):
    return page(request, "app.html", page="create", title="New incident")


@router.get("/incidents/{incident_id}", response_class=HTMLResponse)
def incident(request: Request, incident_id: str):
    return page(request, "app.html", page="incident", title="Incident", resource_id=incident_id)


@router.get("/runbooks", response_class=HTMLResponse)
def runbooks(request: Request):
    return page(request, "app.html", page="runbooks", title="Runbooks")
