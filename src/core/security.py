"""Authentication for Odoo-to-Datum Engine calls."""

from secrets import compare_digest

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


_bearer = HTTPBearer(auto_error=False)


async def require_engine_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Reject calls unless the configured shared bearer secret matches."""
    expected = request.app.state.settings.datum_engine_api_auth_token
    if expected is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Engine authentication is not configured")
    supplied = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
    if not compare_digest(supplied, expected.get_secret_value()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid engine authentication token")
