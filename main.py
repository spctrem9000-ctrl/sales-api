from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from database import init_db
from routers import auth, sync, dashboard, admin, fix_db, cleanup
from websocket_manager import manager

import os
import asyncio
import firebase_admin
from firebase_admin import credentials
import logging

logger = logging.getLogger("uvicorn.error")

import json

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    
    # Initialize Firebase Admin
    key_path = "serviceAccountKey.json"
    firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS")
    
    try:
        if firebase_creds_json:
            cred_dict = json.loads(firebase_creds_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin initialized successfully from FIREBASE_CREDENTIALS env var.")
        elif os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin initialized successfully from serviceAccountKey.json.")
        else:
            logger.warning("Firebase credentials not found. Push notifications will be disabled.")
    except Exception as e:
        logger.error(f"Failed to initialize Firebase Admin: {e}")
        
    try:
        from database import engine, Base, AsyncSessionLocal
        from sqlalchemy import text
        from models import User
        from auth import hash_password
        
        async with AsyncSessionLocal() as db:
            from sqlalchemy.future import select
            
            result = await db.execute(select(User).where(User.username == "super_admin"))
            if not result.scalars().first():
                super_admin = User(
                    username="super_admin",
                    hashed_password=hash_password(os.getenv("SUPER_ADMIN_PASSWORD", "Kareemsobhy@20")),
                    is_superadmin=True
                )
                db.add(super_admin)
                await db.commit()
                logger.info("Super Admin account created.")
    except Exception as e:
        logger.error(f"Failed to recreate database: {e}")

    # Start background tasks
    from tasks import check_expirations
    task = asyncio.create_task(check_expirations())

    yield
    
    task.cancel()


app = FastAPI(
    title="Sales Monitor API",
    description="Real-time branch sales monitoring system",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(sync.router, prefix="/api/sync", tags=["Sync"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(cleanup.router, prefix="/api", tags=["Cleanup"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(fix_db.router, prefix="/api/fix-db", tags=["Fix"])


@app.get("/")
async def root():
    return {"status": "ok", "message": "Sales Monitor API is running"}


import traceback
from fastapi.responses import PlainTextResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    err_msg = f"Unhandled exception: {exc}\n{traceback.format_exc()}"
    logger.error(err_msg)
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": "Internal server error", "traceback": err_msg}, status_code=500)


from sqlalchemy import text
from fastapi import HTTPException, Depends, status
import secrets
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jose import jwt, JWTError
from auth import SECRET_KEY, ALGORITHM

security = HTTPBasic()

# Environment variables for Basic Auth (set these in Railway)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=500, detail="Basic Auth not configured (missing ADMIN_PASSWORD)")
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@app.get("/docs", include_in_schema=False)
async def get_swagger_documentation(username: str = Depends(get_current_username)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")

@app.get("/openapi.json", include_in_schema=False)
async def openapi(username: str = Depends(get_current_username)):
    return get_openapi(title=app.title, version=app.version, routes=app.routes)

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    logger.info("New WebSocket connection attempt")
    # Accept the connection first to read headers, or read headers before accept
    auth_header = websocket.headers.get("authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise JWTError()
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    await manager.connect(websocket)
    logger.info("WebSocket connected!")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        print("WebSocket disconnected")
        manager.disconnect(websocket)
