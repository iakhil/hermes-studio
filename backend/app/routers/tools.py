import re
import subprocess
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.hermes import HermesTools, resolve_hermes_executable, studio_env

router = APIRouter(prefix="/tools")


class ToolSet(BaseModel):
    id: str
    name: str
    icon: str
    enabled: bool
    category: str  # "power", "ai", "productivity", "data"


class ToggleRequest(BaseModel):
    toolset: str
    enabled: bool
    platform: str = "cli"


# Map toolset IDs to categories for the UI
TOOL_CATEGORIES = {
    "browser": "power",
    "terminal": "power",
    "code_execution": "power",
    "vision": "power",
    "tts": "ai",
    "image_gen": "ai",
    "moa": "ai",
    "web": "data",
    "file": "data",
    "session_search": "data",
    "memory": "productivity",
    "skills": "productivity",
    "todo": "productivity",
    "delegation": "productivity",
    "cronjob": "productivity",
    "clarify": "productivity",
    "rl": "ai",
    "homeassistant": "power",
}


def _parse_tools_list(platform: str = "cli") -> list[ToolSet]:
    """Parse output of `hermes tools list` into structured data."""
    try:
        hermes = resolve_hermes_executable() or "hermes"
        result = subprocess.run(
            [hermes, "tools", "list", "--platform", platform],
            capture_output=True,
            text=True,
            timeout=10,
            env=studio_env(),
        )
        if result.returncode != 0:
            return []

        tools = []
        for line in result.stdout.strip().splitlines():
            # Match lines like: "  ✓ enabled  web  🔍 Web Search & Scraping"
            # or: "  ✗ disabled  moa  🧠 Mixture of Agents"
            match = re.match(
                r"\s*[✓✗]\s+(enabled|disabled)\s+(\S+)\s+(\S+)\s+(.*)",
                line,
            )
            if match:
                enabled = match.group(1) == "enabled"
                tool_id = match.group(2)
                icon = match.group(3)
                name = match.group(4).strip()
                tools.append(ToolSet(
                    id=tool_id,
                    name=name,
                    icon=icon,
                    enabled=enabled,
                    category=TOOL_CATEGORIES.get(tool_id, "productivity"),
                ))
        return tools
    except Exception:
        return []


@router.get("", response_model=list[ToolSet])
async def list_tools(platform: str = Query("cli")):
    return _parse_tools_list(platform)


@router.post("/toggle")
async def toggle_tool(req: ToggleRequest):
    action = "enable" if req.enabled else "disable"
    try:
        hermes = resolve_hermes_executable() or "hermes"
        result = subprocess.run(
            [hermes, "tools", action, req.toolset, "--platform", req.platform],
            capture_output=True,
            text=True,
            timeout=10,
            env=studio_env(),
        )
        if result.returncode == 0:
            return {"success": True}
        else:
            return {"success": False, "error": result.stderr.strip()[:200]}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/presets")
async def list_presets():
    return list(HermesTools.PRESETS.values())


@router.post("/presets/{preset_id}/apply")
async def apply_preset(preset_id: str, platform: str = Query("cli")):
    return HermesTools().apply_preset(preset_id, platform)
