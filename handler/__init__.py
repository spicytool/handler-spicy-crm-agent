"""Handler service for CRM agent chat integration.

This package contains the FastAPI handler that receives chat messages
from SpicyTool's frontend and processes them using the deployed
Vertex AI Agent Engine (CRM Agent), streaming responses back via SSE.

Following ADK_VERTEX_AI_GUIDE.md Section 12.2: Handler calls the deployed
agent remotely rather than importing agent code directly.
"""
