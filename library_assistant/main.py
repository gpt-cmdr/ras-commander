from fastapi import FastAPI
from api.logging import router as logging_router

app = FastAPI()

# Include the logging router
app.include_router(logging_router, prefix="/api") 