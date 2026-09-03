from fastapi import APIRouter

from app.api.v1 import auth, battles, challenges, chat, groups, me, media, ws

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(groups.router)
# Challenges live under two prefixes: `/challenges/...` for the resource itself, and
# `/groups/{id}/challenges` for creation/listing inside a group (API_SPEC).
api_router.include_router(challenges.group_challenges_router)
api_router.include_router(challenges.challenges_router)
api_router.include_router(battles.router)
api_router.include_router(media.router)
api_router.include_router(chat.router)
api_router.include_router(ws.router)
