from fastapi import APIRouter
from ops_dashboard.data.database import get_available_filters

router = APIRouter()


@router.get("/options")
def get_filter_options():
    return get_available_filters()
