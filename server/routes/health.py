from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Used by the launcher to know the server is up."""
    return {"status": "ok"}
