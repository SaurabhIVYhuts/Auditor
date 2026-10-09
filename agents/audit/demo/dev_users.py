"""The three development users - must match DEV_USERS in frontend/lib/api.ts.
Development/test only (the backend's temporary header login)."""
import uuid

PRIYA = uuid.UUID("11111111-1111-1111-1111-111111111111")    # auditor (AUD)
RAHUL = uuid.UUID("44444444-4444-4444-4444-444444444444")    # audit manager (AM)
SUNITA = uuid.UUID("55555555-5555-5555-5555-555555555555")   # department owner (OWN)
