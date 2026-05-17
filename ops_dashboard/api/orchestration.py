"""
AI Agent Orchestration Blueprint API.

Serves the structured content for the orchestration explainer tool,
based on the four-layer AI Agent Blueprint:
Skills, MCP, Subagents, Hooks - plus the Core Agent Loop,
Filesystem/Knowledge, and the Plugins packaging layer.
"""
from fastapi import APIRouter

router = APIRouter()


BLUEPRINT = {
    "title": "The Complete AI Agent Blueprint",
    "tagline": "One Framework. Four Layers. Zero Chaos.",
    "layers": [
        {
            "id": "skills",
            "number": 1,
            "name": "Skills",
            "subtitle": "The Intelligence Layer",
            "equation": "Skills = KNOWLEDGE",
            "color": "#f59e0b",
            "summary": "Reusable instruction modules the agent loads on demand.",
            "bullets": [
                "Reusable instruction modules",
                "Loaded ON-DEMAND by the agent",
                "Contain instructions, scripts, resources, templates",
                "Progressive disclosure - agent reads metadata first, "
                "loads full content only when needed",
                "Like TRAINING MANUALS for AI",
            ],
            "flow": [
                "Problem / Goal appears",
                "Agent detects relevant skill",
                "Executes workflow",
                "Loads skill on demand",
            ],
            "note": "Loaded only when needed - like pulling the right manual at the right moment.",
        },
        {
            "id": "mcp",
            "number": 2,
            "name": "MCP",
            "subtitle": "The Connection Layer",
            "equation": "MCP = ABILITY",
            "color": "#3b82f6",
            "summary": "Model Context Protocol servers that connect the agent to external services.",
            "bullets": [
                "Standard protocol for tool & data integration",
                "Each MCP server exposes a capability surface",
                "Agent gains new abilities by attaching a server",
                "Decouples the agent from vendor-specific APIs",
            ],
            "examples": [
                "GitHub", "Notion", "Slack", "GitLab",
                "OpenAI", "AWS", "Database",
            ],
            "note": "Think USB-C: one protocol, many devices.",
        },
        {
            "id": "subagents",
            "number": 3,
            "name": "Subagents",
            "subtitle": "The Execution Layer",
            "equation": "Subagents = DELEGATION",
            "color": "#a855f7",
            "summary": "Specialized agents spawned for isolated tasks with their own toolset.",
            "bullets": [
                "Isolated execution contexts",
                "Each subagent has a narrow role and limited tools",
                "Parent agent delegates and aggregates results",
                "Keeps the main context clean",
            ],
            "examples": [
                {"role": "Code Reviewer", "tools": ["Read", "Grep"]},
                {"role": "Researcher", "tools": ["Search", "Fetch"]},
                {"role": "Deployer", "tools": ["Bash", "SSH"]},
            ],
            "note": "Like a team of specialists - each one good at one thing.",
        },
        {
            "id": "hooks",
            "number": 4,
            "name": "Hooks",
            "subtitle": "The Control Layer",
            "equation": "Hooks = AUTOMATION",
            "color": "#ef4444",
            "summary": "Deterministic event handlers that fire around agent actions.",
            "bullets": [
                "Run BEFORE / AFTER tool execution",
                "Fire when files change or notifications arrive",
                "Add guardrails, alerts, logging, formatting",
                "Pure code - not LLM calls",
            ],
            "types": [
                {"name": "Pre Tool", "desc": "Runs BEFORE tool execution"},
                {"name": "Post Tool", "desc": "Runs AFTER tool execution"},
                {"name": "On Edit", "desc": "Fires when files change"},
                {"name": "On Notification", "desc": "Alerts & logging"},
            ],
            "note": "Block unsafe commits. Run security scan. Auto-format. All deterministic.",
        },
    ],
    "core_loop": {
        "name": "Core Agent Loop",
        "steps": [
            {"name": "Perceive", "desc": "input, context, queries"},
            {"name": "Reason", "desc": "LLM plans next step"},
            {"name": "Act", "desc": "tool call, code exec, API"},
            {"name": "Observe", "desc": "evaluate results"},
            {"name": "Repeat", "desc": "loop back to perceive"},
        ],
        "center": "Agent Core: LLM <-> Tools",
        "foundation": "Instructions & Domain Knowledge / External Tools & Data",
    },
    "knowledge": {
        "title": "Filesystem / Knowledge Sources",
        "anchor": "CLAUDE.md (Always-On Context)",
        "items": ["Skill 1", "Skill 2", "Skill 3", "Reference docs"],
        "mantras": [
            "Skills = What to know",
            "MCP = How to connect",
            "Hooks = When to automate",
        ],
    },
    "plugins": {
        "title": "Plugins - The Packaging Layer",
        "formula": "Skills + MCP + Hooks + Subagents = Plugin",
        "subtitle": "One Package. Bundle and distribute everything.",
    },
    "comparison": [
        {"component": "Skills", "purpose": "Teach expertise & workflows",
         "analogy": "Training Manual"},
        {"component": "MCP", "purpose": "Connect to external services",
         "analogy": "USB-C Port"},
        {"component": "Subagents", "purpose": "Delegate isolated tasks",
         "analogy": "Team Members"},
        {"component": "Hooks", "purpose": "Automate deterministic events",
         "analogy": "Tripwires"},
        {"component": "CLAUDE.md", "purpose": "Always-on project context",
         "analogy": "Sticky Note on Monitor"},
        {"component": "Plugin", "purpose": "Bundle & distribute all above",
         "analogy": "App Package"},
    ],
    "example": {
        "title": "Real-World Example: Competitive Analysis Brief",
        "steps": [
            {"n": 1, "actor": "CLAUDE.md", "action": "loads",
             "detail": "project context, company info"},
            {"n": 2, "actor": "Skill", "action": "activates",
             "detail": "competitive-analysis framework"},
            {"n": 3, "actor": "MCP", "action": "fires",
             "detail": "searches Google Drive for past briefs"},
            {"n": 4, "actor": "Subagent", "action": "spawns",
             "detail": "market-researcher gathers data"},
            {"n": 5, "actor": "Subagent", "action": "spawns",
             "detail": "technical-analyst reviews repos"},
            {"n": 6, "actor": "Hook", "action": "triggers",
             "detail": "auto-formats output, runs linter"},
        ],
    },
}


@router.get("/blueprint")
async def get_blueprint():
    """Return the full AI Agent Blueprint structure."""
    return BLUEPRINT


@router.get("/layers")
async def get_layers():
    """Return just the four core layers."""
    return BLUEPRINT["layers"]


@router.get("/layers/{layer_id}")
async def get_layer(layer_id: str):
    """Return a single layer by id (skills, mcp, subagents, hooks)."""
    for layer in BLUEPRINT["layers"]:
        if layer["id"] == layer_id:
            return layer
    return {"error": f"Unknown layer: {layer_id}"}


@router.get("/example")
async def get_example():
    """Return the step-by-step real-world orchestration example."""
    return BLUEPRINT["example"]
