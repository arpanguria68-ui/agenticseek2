#!/usr/bin/env python3

import os, sys
import uvicorn
import aiofiles
import configparser
import asyncio
import time
import requests
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uuid

from sources.llm_provider import Provider
from sources.interaction import Interaction
from sources.agents import (
    CasualAgent,
    CoderAgent,
    FileAgent,
    PlannerAgent,
    BrowserAgent,
)
from sources.browser import Browser, create_driver
from sources.utility import pretty_print
from sources.logger import Logger
from sources.schemas import QueryRequest, QueryResponse

from dotenv import load_dotenv

load_dotenv()


def is_running_in_docker():
    """Detect if code is running inside a Docker container."""
    # Method 1: Check for .dockerenv file
    if os.path.exists("/.dockerenv"):
        return True

    # Method 2: Check cgroup
    try:
        with open("/proc/1/cgroup", "r") as f:
            return "docker" in f.read()
    except:
        pass

    return False


from celery import Celery

api = FastAPI(title="AgenticSeek API", version="0.1.0")
celery_app = Celery(
    "tasks", broker="redis://localhost:6379/0", backend="redis://localhost:6379/0"
)
celery_app.conf.update(task_track_started=True)
logger = Logger("backend.log")
config = configparser.ConfigParser()
config.read("config.ini")

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists(".screenshots"):
    os.makedirs(".screenshots")
api.mount("/screenshots", StaticFiles(directory=".screenshots"), name="screenshots")


def initialize_system():
    stealth_mode = config.getboolean("BROWSER", "stealth_mode")
    personality_folder = (
        "jarvis" if config.getboolean("MAIN", "jarvis_personality") else "base"
    )
    languages = config["MAIN"]["languages"].split(" ")

    # Force headless mode in Docker containers
    headless = config.getboolean("BROWSER", "headless_browser")
    if is_running_in_docker() and not headless:
        # Print prominent warning to console (visible in docker-compose output)
        print("\n" + "*" * 70)
        print(
            "*** WARNING: Detected Docker environment - forcing headless_browser=True ***"
        )
        print(
            "*** INFO: To see the browser, run 'python cli.py' on your host machine ***"
        )
        print("*" * 70 + "\n")

        # Flush to ensure it's displayed immediately
        sys.stdout.flush()

        # Also log to file
        logger.warning("Detected Docker environment - forcing headless_browser=True")
        logger.info(
            "To see the browser, run 'python cli.py' on your host machine instead"
        )

        headless = True

    provider = Provider(
        provider_name=config["MAIN"]["provider_name"],
        model=config["MAIN"]["provider_model"],
        server_address=config["MAIN"]["provider_server_address"],
        is_local=config.getboolean("MAIN", "is_local"),
    )
    logger.info(f"Provider initialized: {provider.provider_name} ({provider.model})")

    browser = Browser(
        create_driver(headless=headless, stealth_mode=stealth_mode, lang=languages[0]),
        anticaptcha_manual_install=stealth_mode,
    )
    logger.info("Browser initialized")

    agents = [
        CasualAgent(
            name=config["MAIN"]["agent_name"],
            prompt_path=f"prompts/{personality_folder}/casual_agent.txt",
            provider=provider,
            verbose=False,
        ),
        CoderAgent(
            name="coder",
            prompt_path=f"prompts/{personality_folder}/coder_agent.txt",
            provider=provider,
            verbose=False,
        ),
        FileAgent(
            name="File Agent",
            prompt_path=f"prompts/{personality_folder}/file_agent.txt",
            provider=provider,
            verbose=False,
        ),
        BrowserAgent(
            name="Browser",
            prompt_path=f"prompts/{personality_folder}/browser_agent.txt",
            provider=provider,
            verbose=False,
            browser=browser,
        ),
        PlannerAgent(
            name="Planner",
            prompt_path=f"prompts/{personality_folder}/planner_agent.txt",
            provider=provider,
            verbose=False,
            browser=browser,
        ),
    ]
    logger.info("Agents initialized")

    interaction = Interaction(
        agents,
        tts_enabled=config.getboolean("MAIN", "speak"),
        stt_enabled=config.getboolean("MAIN", "listen"),
        recover_last_session=config.getboolean("MAIN", "recover_last_session"),
        langs=languages,
    )
    logger.info("Interaction initialized")
    return interaction


interaction = initialize_system()
is_generating = False
query_resp_history = []


@api.get("/screenshot")
async def get_screenshot():
    logger.info("Screenshot endpoint called")
    screenshot_path = ".screenshots/updated_screen.png"
    if os.path.exists(screenshot_path):
        return FileResponse(screenshot_path)
    logger.error("No screenshot available")
    return JSONResponse(status_code=404, content={"error": "No screenshot available"})


@api.get("/health")
async def health_check():
    logger.info("Health check endpoint called")
    return {"status": "healthy", "version": "0.1.0"}


@api.get("/is_active")
async def is_active():
    logger.info("Is active endpoint called")
    return {"is_active": interaction.is_active, "is_generating": is_generating}


@api.post("/reset")
async def reset_state():
    """Reset the is_generating flag to recover from stuck states"""
    global is_generating
    logger.info("Reset endpoint called")
    is_generating = False
    return JSONResponse(
        status_code=200, content={"status": "reset", "is_generating": False}
    )


@api.get("/stop")
async def stop():
    logger.info("Stop endpoint called")
    if interaction.current_agent is None:
        return JSONResponse(
            status_code=404, content={"error": "No active agent to stop"}
        )
    interaction.current_agent.request_stop()
    return JSONResponse(status_code=200, content={"status": "stopped"})


@api.post("/session/clear")
async def clear_session():
    """Clear all agent memories to start a fresh session."""
    logger.info("Session clear endpoint called")
    try:
        for agent in interaction.agents:
            agent.memory.clear()
        return JSONResponse(
            status_code=200,
            content={
                "status": "session_cleared",
                "message": "All agent memories cleared",
            },
        )
    except Exception as e:
        logger.error(f"Error clearing session: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@api.post("/session/save")
async def save_session():
    """Force save current session."""
    logger.info("Session save endpoint called")
    try:
        interaction.save_session()
        return JSONResponse(
            status_code=200,
            content={
                "status": "session_saved",
                "message": "Session saved successfully",
            },
        )
    except Exception as e:
        logger.error(f"Error saving session: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@api.get("/session/info")
async def get_session_info():
    """Get information about current session state."""
    logger.info("Session info endpoint called")
    try:
        session_info = {
            "agents": [],
            "is_generating": is_generating,
            "current_agent": (
                interaction.current_agent.agent_name
                if interaction.current_agent
                else None
            ),
        }
        for agent in interaction.agents:
            session_info["agents"].append(
                {
                    "type": agent.type,
                    "name": agent.agent_name,
                    "memory_messages": len(agent.memory.get()),
                }
            )
        return JSONResponse(status_code=200, content=session_info)
    except Exception as e:
        logger.error(f"Error getting session info: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@api.get("/sessions")
async def list_sessions():
    """List all saved chat sessions with metadata."""
    logger.info("List sessions endpoint called")
    try:
        sessions = []
        conversations_dir = "conversations"

        # Use the planner_agent folder as the source of truth for session listing
        planner_dir = os.path.join(conversations_dir, "planner_agent")
        if not os.path.exists(planner_dir):
            return JSONResponse(status_code=200, content={"sessions": []})

        for filename in os.listdir(planner_dir):
            if filename.startswith("memory_") and filename.endswith(".txt"):
                filepath = os.path.join(planner_dir, filename)
                try:
                    # Extract session ID from filename (the timestamp part)
                    session_id = filename.replace("memory_", "").replace(".txt", "")

                    # Get file modification time
                    mtime = os.path.getmtime(filepath)

                    # Read first few messages for preview
                    with open(filepath, "r") as f:
                        content = f.read()
                        import json

                        messages = json.loads(content)

                        # Get preview from first user message
                        preview = "No messages"
                        message_count = len(messages)
                        for msg in messages:
                            if msg.get("role") == "user":
                                preview = msg.get("content", "")[:100]
                                if len(msg.get("content", "")) > 100:
                                    preview += "..."
                                break

                        sessions.append(
                            {
                                "session_id": session_id,
                                "filename": filename,
                                "created_at": session_id,  # Format: YYYY-MM-DD_HH-MM-SS
                                "modified_at": mtime,
                                "message_count": message_count,
                                "preview": preview,
                            }
                        )
                except Exception as e:
                    logger.warning(f"Error reading session file {filename}: {e}")
                    continue

        # Sort by modification time, newest first
        sessions.sort(key=lambda x: x["modified_at"], reverse=True)

        return JSONResponse(status_code=200, content={"sessions": sessions})
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@api.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get details of a specific session."""
    logger.info(f"Get session endpoint called for: {session_id}")
    try:
        import json

        session_data = {"agents": {}}

        conversations_dir = "conversations"
        agent_types = [
            "casual_agent",
            "code_agent",
            "file_agent",
            "browser_agent",
            "planner_agent",
        ]

        for agent_type in agent_types:
            filepath = os.path.join(
                conversations_dir, agent_type, f"memory_{session_id}.txt"
            )
            if os.path.exists(filepath):
                with open(filepath, "r") as f:
                    content = f.read()
                    messages = json.loads(content)
                    session_data["agents"][agent_type] = {
                        "message_count": len(messages),
                        "messages": messages,
                    }

        if not session_data["agents"]:
            return JSONResponse(status_code=404, content={"error": "Session not found"})

        session_data["session_id"] = session_id
        return JSONResponse(status_code=200, content=session_data)
    except Exception as e:
        logger.error(f"Error getting session {session_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@api.post("/sessions/new")
async def create_new_session():
    """Save current session and start a new one."""
    logger.info("Create new session endpoint called")
    try:
        # Save current session first
        interaction.save_session()

        # Clear all agent memories
        for agent in interaction.agents:
            agent.memory.clear()

        # Reset session time in memory objects to create new session files
        import datetime

        new_session_time = datetime.datetime.now()
        for agent in interaction.agents:
            agent.memory.session_time = new_session_time

        new_session_id = new_session_time.strftime("%Y-%m-%d_%H-%M-%S")

        return JSONResponse(
            status_code=200,
            content={
                "status": "new_session_created",
                "session_id": new_session_id,
                "message": "Previous session saved, new session started",
            },
        )
    except Exception as e:
        logger.error(f"Error creating new session: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@api.post("/sessions/{session_id}/load")
async def load_session(session_id: str):
    """Load a specific session into memory."""
    logger.info(f"Load session endpoint called for: {session_id}")
    try:
        import json

        # First save current session
        interaction.save_session()

        conversations_dir = "conversations"
        agent_types = [
            "casual_agent",
            "code_agent",
            "file_agent",
            "browser_agent",
            "planner_agent",
        ]
        loaded_count = 0

        for agent in interaction.agents:
            filepath = os.path.join(
                conversations_dir, agent.type, f"memory_{session_id}.txt"
            )
            if os.path.exists(filepath):
                with open(filepath, "r") as f:
                    content = f.read()
                    messages = json.loads(content)
                    if messages and isinstance(messages, list):
                        agent.memory.memory = messages
                        loaded_count += 1
                        logger.info(f"Loaded {len(messages)} messages for {agent.type}")

        if loaded_count == 0:
            return JSONResponse(status_code=404, content={"error": "Session not found"})

        return JSONResponse(
            status_code=200,
            content={
                "status": "session_loaded",
                "session_id": session_id,
                "agents_loaded": loaded_count,
                "message": f"Loaded session {session_id}",
            },
        )
    except Exception as e:
        logger.error(f"Error loading session {session_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@api.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a specific session."""
    logger.info(f"Delete session endpoint called for: {session_id}")
    try:
        conversations_dir = "conversations"
        agent_types = [
            "casual_agent",
            "code_agent",
            "file_agent",
            "browser_agent",
            "planner_agent",
        ]
        deleted_count = 0

        for agent_type in agent_types:
            filepath = os.path.join(
                conversations_dir, agent_type, f"memory_{session_id}.txt"
            )
            if os.path.exists(filepath):
                os.remove(filepath)
                deleted_count += 1
                logger.info(f"Deleted session file: {filepath}")

        if deleted_count == 0:
            return JSONResponse(status_code=404, content={"error": "Session not found"})

        return JSONResponse(
            status_code=200,
            content={
                "status": "session_deleted",
                "session_id": session_id,
                "files_deleted": deleted_count,
            },
        )
    except Exception as e:
        logger.error(f"Error deleting session {session_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============ Workspace File Browser Endpoints ============

WORKSPACE_DIR = "/opt/workspace"


@api.get("/files")
async def list_workspace_files(path: str = ""):
    """List files and folders in the workspace directory."""
    logger.info(f"List files endpoint called for path: {path}")
    try:
        # Sanitize path to prevent directory traversal
        safe_path = os.path.normpath(path).lstrip("/\\")
        if ".." in safe_path:
            return JSONResponse(status_code=400, content={"error": "Invalid path"})

        full_path = os.path.join(WORKSPACE_DIR, safe_path)

        if not os.path.exists(full_path):
            return JSONResponse(status_code=404, content={"error": "Path not found"})

        if not os.path.isdir(full_path):
            return JSONResponse(
                status_code=400, content={"error": "Path is not a directory"}
            )

        items = []
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            stat = os.stat(item_path)
            items.append(
                {
                    "name": item,
                    "path": os.path.join(safe_path, item) if safe_path else item,
                    "is_dir": os.path.isdir(item_path),
                    "size": stat.st_size if os.path.isfile(item_path) else None,
                    "modified": stat.st_mtime,
                }
            )

        # Sort: directories first, then by name
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        return JSONResponse(
            status_code=200,
            content={
                "path": safe_path,
                "items": items,
                "parent": os.path.dirname(safe_path) if safe_path else None,
            },
        )
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@api.get("/files/view")
async def view_file_content(path: str):
    """View the contents of a text file."""
    logger.info(f"View file endpoint called for: {path}")
    try:
        # Sanitize path
        safe_path = os.path.normpath(path).lstrip("/\\")
        if ".." in safe_path:
            return JSONResponse(status_code=400, content={"error": "Invalid path"})

        full_path = os.path.join(WORKSPACE_DIR, safe_path)

        if not os.path.exists(full_path):
            return JSONResponse(status_code=404, content={"error": "File not found"})

        if os.path.isdir(full_path):
            return JSONResponse(
                status_code=400, content={"error": "Cannot view directory"}
            )

        # Check file size (limit to 1MB for text viewing)
        file_size = os.path.getsize(full_path)
        if file_size > 1024 * 1024:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "File too large to view",
                    "size": file_size,
                    "message": "Use download instead",
                },
            )

        # Try to read as text
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Detect file type
            ext = os.path.splitext(full_path)[1].lower()
            file_type = "text"
            if ext in [".py"]:
                file_type = "python"
            elif ext in [".js", ".jsx"]:
                file_type = "javascript"
            elif ext in [".json"]:
                file_type = "json"
            elif ext in [".md"]:
                file_type = "markdown"
            elif ext in [".html", ".htm"]:
                file_type = "html"
            elif ext in [".css"]:
                file_type = "css"
            elif ext in [".sh"]:
                file_type = "shell"

            return JSONResponse(
                status_code=200,
                content={
                    "path": safe_path,
                    "name": os.path.basename(full_path),
                    "content": content,
                    "size": file_size,
                    "type": file_type,
                },
            )
        except UnicodeDecodeError:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Binary file cannot be viewed as text",
                    "message": "Use download instead",
                },
            )
    except Exception as e:
        logger.error(f"Error viewing file: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


from fastapi.responses import FileResponse


@api.get("/files/download")
async def download_file(path: str):
    """Download a file from the workspace."""
    logger.info(f"Download file endpoint called for: {path}")
    try:
        # Sanitize path
        safe_path = os.path.normpath(path).lstrip("/\\")
        if ".." in safe_path:
            return JSONResponse(status_code=400, content={"error": "Invalid path"})

        full_path = os.path.join(WORKSPACE_DIR, safe_path)

        if not os.path.exists(full_path):
            return JSONResponse(status_code=404, content={"error": "File not found"})

        if os.path.isdir(full_path):
            return JSONResponse(
                status_code=400, content={"error": "Cannot download directory"}
            )

        filename = os.path.basename(full_path)
        return FileResponse(
            path=full_path, filename=filename, media_type="application/octet-stream"
        )
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# LLM Settings Models
class LLMSettings(BaseModel):
    provider_name: str = "lm-studio"
    provider_model: str = ""
    provider_server_address: str = "http://127.0.0.1:1234"
    is_local: bool = True


class ConnectionCheckRequest(BaseModel):
    provider_name: str
    server_address: str


@api.get("/llm/settings")
async def get_llm_settings():
    """Get current LLM provider settings from config.ini"""
    logger.info("Getting LLM settings")
    try:
        config.read("config.ini")
        return {
            "provider_name": config.get("MAIN", "provider_name", fallback="lm-studio"),
            "provider_model": config.get("MAIN", "provider_model", fallback=""),
            "provider_server_address": config.get(
                "MAIN", "provider_server_address", fallback="http://127.0.0.1:1234"
            ),
            "is_local": config.getboolean("MAIN", "is_local", fallback=True),
        }
    except Exception as e:
        logger.error(f"Error reading config: {str(e)}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@api.post("/llm/settings")
async def save_llm_settings(settings: LLMSettings):
    """Save LLM provider settings to config.ini"""
    logger.info(f"Saving LLM settings: {settings}")
    try:
        config.read("config.ini")
        config.set("MAIN", "provider_name", settings.provider_name)
        config.set("MAIN", "provider_model", settings.provider_model)
        config.set("MAIN", "provider_server_address", settings.provider_server_address)
        config.set("MAIN", "is_local", str(settings.is_local))

        with open("config.ini", "w") as configfile:
            config.write(configfile)

        logger.info("LLM settings saved successfully")
        return {
            "status": "success",
            "message": "Settings saved. Restart backend to apply.",
        }
    except Exception as e:
        logger.error(f"Error saving config: {str(e)}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@api.post("/llm/check-connection")
async def check_llm_connection(request: ConnectionCheckRequest):
    """Check connection to LLM provider and list available models"""
    logger.info(
        f"Checking connection to {request.provider_name} at {request.server_address}"
    )

    # Handle Docker internal URL mapping
    server_address = request.server_address
    if is_running_in_docker():
        # Replace localhost/127.0.0.1 with host.docker.internal for Docker
        internal_url = os.getenv("DOCKER_INTERNAL_URL", "http://host.docker.internal")
        if "127.0.0.1" in server_address or "localhost" in server_address:
            # Extract port from the address
            if ":" in server_address.split("//")[-1]:
                port = server_address.split(":")[-1]
                server_address = f"{internal_url}:{port}"
            else:
                server_address = internal_url
            logger.info(f"Docker detected, using internal URL: {server_address}")

    try:
        models = []

        if request.provider_name == "lm-studio":
            # LM Studio uses OpenAI-compatible API
            url = f"{server_address}/v1/models"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                models = [
                    m.get("id", m.get("name", "unknown")) for m in data.get("data", [])
                ]
                return {
                    "connected": True,
                    "message": f"Connected to LM Studio. Found {len(models)} model(s).",
                    "models": models,
                }
            else:
                return {
                    "connected": False,
                    "message": f"LM Studio returned status {response.status_code}",
                    "models": [],
                }

        elif request.provider_name == "ollama":
            # Ollama uses its own API
            url = (
                f"http://{server_address}/api/tags"
                if not server_address.startswith("http")
                else f"{server_address}/api/tags"
            )
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                models = [m.get("name", "unknown") for m in data.get("models", [])]
                return {
                    "connected": True,
                    "message": f"Connected to Ollama. Found {len(models)} model(s).",
                    "models": models,
                }
            else:
                return {
                    "connected": False,
                    "message": f"Ollama returned status {response.status_code}",
                    "models": [],
                }

        else:
            # Generic OpenAI-compatible check
            url = (
                f"{server_address}/v1/models"
                if not server_address.endswith("/v1/models")
                else server_address
            )
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                models = [
                    m.get("id", m.get("name", "unknown")) for m in data.get("data", [])
                ]
                return {
                    "connected": True,
                    "message": f"Connected. Found {len(models)} model(s).",
                    "models": models,
                }
            else:
                return {
                    "connected": False,
                    "message": f"Server returned status {response.status_code}",
                    "models": [],
                }

    except requests.exceptions.Timeout:
        logger.warning(f"Connection timeout to {server_address}")
        return {
            "connected": False,
            "message": "Connection timed out. Is the server running?",
            "models": [],
        }
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"Connection error to {server_address}: {str(e)}")
        return {
            "connected": False,
            "message": f"Cannot connect. Make sure {request.provider_name} is running.",
            "models": [],
        }
    except Exception as e:
        logger.error(f"Error checking connection: {str(e)}")
        return {"connected": False, "message": f"Error: {str(e)}", "models": []}


@api.get("/latest_answer")
async def get_latest_answer():
    global query_resp_history
    if interaction.current_agent is None:
        return JSONResponse(status_code=404, content={"error": "No agent available"})
    uid = str(uuid.uuid4())
    if not any(
        q["answer"] == interaction.current_agent.last_answer for q in query_resp_history
    ):
        query_resp = {
            "done": "false",
            "answer": interaction.current_agent.last_answer,
            "reasoning": interaction.current_agent.last_reasoning,
            "agent_name": (
                interaction.current_agent.agent_name
                if interaction.current_agent
                else "None"
            ),
            "success": interaction.current_agent.success,
            "blocks": (
                {
                    f"{i}": block.jsonify()
                    for i, block in enumerate(interaction.get_last_blocks_result())
                }
                if interaction.current_agent
                else {}
            ),
            "status": (
                interaction.current_agent.get_status_message
                if interaction.current_agent
                else "No status available"
            ),
            "uid": uid,
        }
        interaction.current_agent.last_answer = ""
        interaction.current_agent.last_reasoning = ""
        query_resp_history.append(query_resp)
        return JSONResponse(status_code=200, content=query_resp)
    if query_resp_history:
        return JSONResponse(status_code=200, content=query_resp_history[-1])
    return JSONResponse(status_code=404, content={"error": "No answer available"})


async def think_wrapper(interaction, query):
    try:
        interaction.last_query = query
        logger.info("Agents request is being processed")
        success = await interaction.think()
        if not success:
            interaction.last_answer = "Error: No answer from agent"
            interaction.last_reasoning = "Error: No reasoning from agent"
            interaction.last_success = False
        else:
            interaction.last_success = True
        pretty_print(interaction.last_answer)
        interaction.speak_answer()
        return success
    except Exception as e:
        logger.error(f"Error in think_wrapper: {str(e)}")
        interaction.last_answer = f""
        interaction.last_reasoning = f"Error: {str(e)}"
        interaction.last_success = False
        raise e


@api.post("/query", response_model=QueryResponse)
async def process_query(request: QueryRequest):
    global is_generating, query_resp_history
    logger.info(f"Processing query: {request.query}")
    query_resp = QueryResponse(
        done="false",
        answer="",
        reasoning="",
        agent_name="Unknown",
        success="false",
        blocks={},
        status="Ready",
        uid=str(uuid.uuid4()),
    )
    if is_generating:
        logger.warning("Another query is being processed, please wait.")
        return JSONResponse(status_code=429, content=query_resp.jsonify())

    try:
        is_generating = True
        success = await think_wrapper(interaction, request.query)
        is_generating = False

        if not success:
            query_resp.answer = interaction.last_answer
            query_resp.reasoning = interaction.last_reasoning
            return JSONResponse(status_code=400, content=query_resp.jsonify())

        if interaction.current_agent:
            blocks_json = {
                f"{i}": block.jsonify()
                for i, block in enumerate(interaction.current_agent.get_blocks_result())
            }
        else:
            logger.error("No current agent found")
            blocks_json = {}
            query_resp.answer = "Error: No current agent"
            return JSONResponse(status_code=400, content=query_resp.jsonify())

        logger.info(f"Answer: {interaction.last_answer}")
        logger.info(f"Blocks: {blocks_json}")
        query_resp.done = "true"
        query_resp.answer = interaction.last_answer
        query_resp.reasoning = interaction.last_reasoning
        query_resp.agent_name = interaction.current_agent.agent_name
        query_resp.success = str(interaction.last_success)
        query_resp.blocks = blocks_json

        query_resp_dict = {
            "done": query_resp.done,
            "answer": query_resp.answer,
            "agent_name": query_resp.agent_name,
            "success": query_resp.success,
            "blocks": query_resp.blocks,
            "status": query_resp.status,
            "uid": query_resp.uid,
        }
        query_resp_history.append(query_resp_dict)

        logger.info("Query processed successfully")
        return JSONResponse(status_code=200, content=query_resp.jsonify())
    except Exception as e:
        is_generating = False  # Reset flag on error to prevent 429 lockout
        logger.error(f"An error occurred: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e),
                "message": "An unexpected error occurred processing the query.",
            },
        )
    finally:
        is_generating = False  # Ensure flag is always reset
        logger.info("Processing finished")
        if config.getboolean("MAIN", "save_session"):
            interaction.save_session()


if __name__ == "__main__":
    # Print startup info
    if is_running_in_docker():
        print("[AgenticSeek] Starting in Docker container...")
    else:
        print("[AgenticSeek] Starting on host machine...")

    envport = os.getenv("BACKEND_PORT")
    if envport:
        port = int(envport)
    else:
        port = 7777
    uvicorn.run(api, host="0.0.0.0", port=7777)
