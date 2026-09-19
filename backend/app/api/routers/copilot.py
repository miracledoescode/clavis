"""Co-Pilot — the web approve/reject surface + RLHF (agent_logs) history.

  GET  /v1/copilot/proposals              the caller's pending proposals
  GET  /v1/copilot/decisions               the caller's decision history
  POST /v1/copilot/proposals/{id}/approve  approve a pending proposal
  POST /v1/copilot/proposals/{id}/reject   reject a pending proposal

Reads go straight to PostgREST under the caller's own JWT (RLS-scoped, via
`copilot_store`). Writes do NOT touch agent_logs directly — they resolve the
proposal to the AgentLoop that owns it (the SAME `AgentLoopRegistry` the
Telegram webhook uses) and call `AgentLoop.on_approval` / `on_rejection`
directly, so web and Telegram share one execution path and one idempotency
gate. A caller can only act on a proposal_id they own: the RLS-scoped
ownership check below is required here (unlike Telegram, which is a single
global chat in V0) so one user cannot approve/reject another user's proposal
by guessing an id.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.api.models import RejectProposalRequest
from app.api.routers.telegram import get_agent_loop_registry
from app.engine import copilot_store
from app.engine.agent_loop import AgentLoopRegistry

router = APIRouter(prefix="/v1/copilot", tags=["co-pilot"])


@router.get("/proposals")
async def list_proposals(principal: dict = Depends(get_current_user)) -> list:
    return await copilot_store.list_pending_proposals(principal["token"])


@router.get("/decisions")
async def list_decisions(
    limit: int = 50, offset: int = 0, principal: dict = Depends(get_current_user)
) -> list:
    return await copilot_store.list_decisions(principal["token"], limit=limit, offset=offset)


async def _owned_loop(proposal_id: str, principal: dict, registry: AgentLoopRegistry):
    """The AgentLoop for `proposal_id`, after confirming the caller owns it and
    it's still pending. Raises 404/409 otherwise."""
    row = await copilot_store.get_pending_proposal(proposal_id, principal["token"])
    if row is None:
        # RLS hides other users' rows, so this also covers "not yours".
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

    loop = await registry.get_loop_for_proposal(proposal_id)
    if loop is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Proposal is no longer active (expired or already resolved)",
        )
    return loop


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str,
    principal: dict = Depends(get_current_user),
    registry: AgentLoopRegistry = Depends(get_agent_loop_registry),
) -> dict:
    loop = await _owned_loop(proposal_id, principal, registry)
    used_keys = await loop.state_store.used_idempotency_keys()
    await loop.on_approval(proposal_id, used_keys)
    return {"proposal_id": proposal_id, "status": "approved"}


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    req: RejectProposalRequest,
    principal: dict = Depends(get_current_user),
    registry: AgentLoopRegistry = Depends(get_agent_loop_registry),
) -> dict:
    loop = await _owned_loop(proposal_id, principal, registry)
    await loop.on_rejection(proposal_id, req.reason_chip)
    return {"proposal_id": proposal_id, "status": "rejected"}
