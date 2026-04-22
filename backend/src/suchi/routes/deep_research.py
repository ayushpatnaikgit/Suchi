"""Deep Research API routes."""

import asyncio
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..deep_research import deep_research, research_gaps, DeepResearchResult

router = APIRouter(prefix="/api/deep-research", tags=["deep-research"])


class DeepResearchRequest(BaseModel):
    query: str
    collection_id: str | None = None
    entry_id: str | None = None
    tier: str = "quick"  # "quick" or "max"
    previous_interaction_id: str | None = None


class GapsRequest(BaseModel):
    collection_id: str
    tier: str = "quick"


def _result_to_dict(result: DeepResearchResult) -> dict:
    return {
        "report": result.report,
        "sources_count": result.sources_count,
        "discovered_papers": result.discovered_papers,
        "duration_seconds": result.duration_seconds,
        "interaction_id": result.interaction_id,
        "tier": result.tier,
    }


@router.post("")
async def run_deep_research(req: DeepResearchRequest):
    """Run a Deep Research query.

    First answer from the library (handled by the frontend before calling this).
    This endpoint only does the web research part.
    """
    try:
        result = await deep_research(
            query=req.query,
            collection_id=req.collection_id,
            entry_id=req.entry_id,
            tier=req.tier,
            previous_interaction_id=req.previous_interaction_id,
        )
        return _result_to_dict(result)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except ImportError as e:
        raise HTTPException(500, str(e))
    except TimeoutError as e:
        raise HTTPException(504, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@router.post("/gaps")
async def find_gaps(req: GapsRequest):
    """Analyze a collection for gaps and missing papers."""
    try:
        result = await research_gaps(
            collection_id=req.collection_id,
            tier=req.tier,
        )
        return _result_to_dict(result)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except ImportError as e:
        raise HTTPException(500, str(e))
    except TimeoutError as e:
        raise HTTPException(504, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
