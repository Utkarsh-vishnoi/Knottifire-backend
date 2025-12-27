"""
Authentication and authorization utilities.
"""

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import config


# Webhook API key authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    Verify webhook API key.
    Raises 401 if invalid or missing.
    """
    if not api_key or api_key != config.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return api_key


# ACK bearer token authentication
bearer_scheme = HTTPBearer(auto_error=False)


async def verify_ack_token(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)) -> str:
    """
    Verify ACK bearer token.
    Raises 401 if invalid or missing.
    """
    if not credentials or credentials.credentials != config.ACK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization token",
        )
    return credentials.credentials
