import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import core.config as config

security = HTTPBasic()


def verify_user(credentials: HTTPBasicCredentials = Depends(security)):
    # Read from the config module (not a by-value import) so credential changes
    # take effect without editing this file.
    is_user_ok = secrets.compare_digest(credentials.username, config.ADMIN_USER)
    is_pass_ok = secrets.compare_digest(credentials.password, config.ADMIN_PASS)
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
