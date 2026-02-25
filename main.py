from __future__ import annotations

import asyncio
import json
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


# =========================
# Helpers
# =========================
def now_ts() -> int:
    return int(time.time())


def gen_room_id(n: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def gen_id(n: int = 16) -> str:
    return secrets.token_hex(n // 2)


# =========================
# Models
# =========================
@dataclass
class Player:
    player_id: str
    key: str
    name: str
    is_host: bool = False
    connected: bool = True
    alive: bool = True
    balls_left: int = 3
    hand_submitted: bool = False
    guess_submitted: bool = False
    reaction: str = ""
    ws: Optional[WebSocket] = None


@dataclass
class Room:
    room_id: str
    players: Dict[str, Player] = field(default_factory=dict)
    host_player_id: str = ""
    phase: str = "lobby"  # lobby | hands | guesses | reveal | over
    round_num: int = 0
    paused: bool = False

    prize: str = ""
    join_order: List[str] = field(default_factory=list)

    # round state
    round_order: List[str] = field(default_factory=list)
    turn_idx: int = 0
    hands: Dict[str, int] = field(default_factory=dict)
    guesses: Dict[str, int] = field(default_factory=dict)

    used_guesses: List[int] = field(default_factory=list)
    guesses_public: List[dict] = field(default_factory=list)


rooms: Dict[str, Room] = {}
rooms_lock = asyncio.Lock()


# =========================
# FastAPI
# =========================
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api/create-room")
async def create_room():
    async with rooms_lock:
        rid = gen_room_id()
        while rid in rooms:
            rid = gen_room_id()
        rooms[rid] = Room(room_id=rid)
    return JSONResponse({"room_id": rid})


# =========================
# State serialization
# =========================
def room_state(room: Room) -> dict:
    # round_order as list of {player_id, name}
    ro = []
    for pid in room.round_order:
        p = room.players.get(pid)
        if p:
            ro.append({"player_id": p.player_id, "name": p.name})

    turn_pid = room.round_order[room.turn_idx] if room.round_order and room.turn_idx < len(room.round_order) else ""
    turn_name = room.players[turn_pid].name if turn_pid and turn_pid in room.players else ""

    max_guess = sum(room.players[pid].balls_left for pid in room.round_order if pid in room.players and room.players[pid].alive)

    return {
        "room_id": room.room_id,
        "phase": room.phase,
        "round_num": room.round_num,
        "paused": room.paused,
        "prize": room.prize,

        "host_player_id": room.host_player_id,
        "turn_player_id": turn_pid,
        "turn_player_name": turn_name,

        "round_order": ro,

        "max_guess": max_guess,
        "used_guesses": room.used_guesses,
        "guesses_public": room.guesses_public,

        "players": [
            {
                "player_id": p.player_id,
                "name": p.name,
                "is_host": p.is_host,
                "connected": p.connected,
                "alive": p.alive,
                "balls_left": p.balls_left,
                "hand_submitted": p.hand_submitted,
                "guess_submitted": p.guess_submitted,
                "reaction": p.reaction,
            }
            for p in room.players.values()
        ],
    }


async def _safe_send(ws: WebSocket, data: dict):
    try:
        await ws.send_text(json.dumps(data))
    except Exception:
        pass


async def _broadcast_state(room: Room):
    payload = {"type": "state", "state": room_state(room)}
    for p in list(room.players.values()):
        if p.ws and p.connected:
            await _safe_send(p.ws, payload)


async def _send_error(ws: WebSocket, message: str):
    await _safe_send(ws, {"type": "error", "message": message})


def _ensure_host(room: Room):
    if room.host_player_id in room.players:
        return
    # pick first connected/alive, else any
    for pid in room.join_order:
        if pid in room.players and room.players[pid].connected:
            room.host_player_id = pid
            room.players[pid].is_host = True
            return
    for pid, p in room.players.items():
        room.host_player_id = pid
        p.is_host = True
        return


def _alive_ids(room: Room) -> List[str]:
    return [pid for pid in room.join_order if pid in room.players and room.players[pid].alive]


def _reset_round(room: Room):
    room.hands.clear()
    room.guesses.clear()
    room.used_guesses = []
    room.guesses_public = []
    for p in room.players.values():
        p.hand_submitted = False
        p.guess_submitted = False


def _build_round_order(room: Room):
    alive = _alive_ids(room)
    if not alive:
        room.round_order = []
        room.turn_idx = 0
        return

    # rotate first player each round
    # pick start based on round_num
    start = (room.round_num - 1) % len(alive) if room.round_num > 0 else 0
    room.round_order = alive[start:] + alive[:start]
    room.turn_idx = 0


def _advance_turn(room: Room):
    if not room.round_order:
        return
    room.turn_idx += 1
    if room.turn_idx >= len(room.round_order):
        room.turn_idx = 0


def _all_submitted(room: Room, phase: str) -> bool:
    for pid in room.round_order:
        p = room.players.get(pid)
        if not p or not p.alive:
            continue
        if phase == "hands" and not p.hand_submitted:
            return False
        if phase == "guesses" and not p.guess_submitted:
            return False
    return True


def _winner_names(room: Room, total: int) -> List[str]:
    winners = []
    for pid, guess in room.guesses.items():
        p = room.players.get(pid)
        if p and p.alive and guess == total:
            winners.append(p.name)
    return winners


def _apply_winners_lose_ball(room: Room, winners: List[str]):
    for pid, p in room.players.items():
        if p.name in winners and p.alive:
            p.balls_left = max(0, p.balls_left - 1)
            if p.balls_left == 0:
                p.alive = False


def _game_over(room: Room) -> Optional[dict]:
    alive = [p for p in room.players.values() if p.alive]
    if len(alive) == 1 and len(room.players) >= 2:
        return {"loser": alive[0].name}
    return None


# =========================
# WebSocket
# =========================
@app.websocket("/ws/{room_id}")
async def ws_room(ws: WebSocket, room_id: str, name: str = "Jogador", key: str = ""):
    await ws.accept()

    room_id = (room_id or "").strip().upper()
    name = (name or "Jogador").strip()[:24]

    async with rooms_lock:
        room = rooms.get(room_id)
        if not room:
            await _send_error(ws, "Sala não existe.")
            await ws.close()
            return

        # reconnect by key
        if key:
            for p in room.players.values():
                if p.key == key:
                    p.ws = ws
                    p.connected = True
                    # keep name from query (optional)
                    if name:
                        p.name = name
                    await _safe_send(ws, {"type": "joined", "player_id": p.player_id, "room_id": room.room_id, "player_key": p.key})
                    await _broadcast_state(room)
                    player = p
                    break
            else:
                player = None
        else:
            player = None

        if player is None:
            # new player
            if len(room.players) >= 10:
                await _send_error(ws, "Sala cheia (máx 10).")
                await ws.close()
                return

            pid = gen_id(12)
            pkey = gen_id(16)
            is_host = len(room.players) == 0

            player = Player(
                player_id=pid,
                key=pkey,
                name=name,
                is_host=is_host,
                connected=True,
                alive=True,
                balls_left=3,
                ws=ws,
            )

            room.players[pid] = player
            room.join_order.append(pid)
            if is_host:
                room.host_player_id = pid

            await _safe_send(ws, {"type": "joined", "player_id": pid, "room_id": room.room_id, "player_key": pkey})
            await _broadcast_state(room)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            mtype = (msg.get("type") or "").strip()

            async with rooms_lock:
                room = rooms.get(room_id)
                if not room:
                    await _send_error(ws, "Sala não existe mais.")
                    await ws.close()
                    return

                # player can disappear (kicked)
                if player.player_id not in room.players:
                    await _send_error(ws, "Você foi removido da sala.")
                    await ws.close()
                    return

                # refresh reference
                player = room.players[player.player_id]

                # keepalive
                if mtype == "ping":
                    await _safe_send(ws, {"type": "pong"})
                    continue

                # chat
                if mtype == "chat":
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    text = text[:220]
                    payload = {"type": "chat", "name": player.name, "text": text, "ts": now_ts()}
                    for p in list(room.players.values()):
                        if p.ws and p.connected:
                            await _safe_send(p.ws, payload)
                    continue

                # react
                if mtype == "react":
                    emoji = (msg.get("emoji") or "").strip()
                    if emoji not in ("🙂", "😭", "😡", ""):
                        continue
                    player.reaction = emoji
                    await _broadcast_state(room)
                    continue

                # host-only controls
                if mtype in ("start", "restart", "skip", "pause", "set_prize", "kick"):
                    if room.host_player_id != player.player_id:
                        await _send_error(ws, "Só o host pode fazer isso.")
                        continue

                # ✅ kick (expulsar)
                if mtype == "kick":
                    target_id = (msg.get("target_id") or "").strip()
                    if not target_id or target_id not in room.players:
                        continue
                    if target_id == player.player_id:
                        await _send_error(ws, "Você não pode expulsar você mesmo.")
                        continue
                    if target_id == room.host_player_id:
                        await _send_error(ws, "Não dá pra expulsar o host.")
                        continue

                    target = room.players.get(target_id)
                    tws = target.ws if target else None

                    # limpar round state
                    room.hands.pop(target_id, None)
                    room.guesses.pop(target_id, None)
                    room.round_order = [pid for pid in room.round_order if pid != target_id]
                    if room.turn_idx >= len(room.round_order):
                        room.turn_idx = 0

                    # remove
                    if target_id in room.join_order:
                        room.join_order.remove(target_id)
                    room.players.pop(target_id, None)

                    _ensure_host(room)
                    await _broadcast_state(room)

                    if tws:
                        await _safe_send(tws, {"type": "error", "message": "Você foi expulso da sala."})
                        try:
                            await tws.close()
                        except Exception:
                            pass
                    continue

                if mtype == "set_prize":
                    val = (msg.get("value") or "").strip()
                    room.prize = val[:80]
                    await _broadcast_state(room)
                    continue

                if mtype == "pause":
                    room.paused = not room.paused
                    await _broadcast_state(room)
                    continue

                if mtype == "restart":
                    # reset full game
                    room.phase = "lobby"
                    room.round_num = 0
                    room.paused = False
                    room.prize = room.prize  # mantém
                    for p in room.players.values():
                        p.alive = True
                        p.balls_left = 3
                        p.hand_submitted = False
                        p.guess_submitted = False
                    room.round_order = []
                    room.turn_idx = 0
                    _reset_round(room)
                    await _broadcast_state(room)
                    continue

                if mtype == "start":
                    if room.phase != "lobby":
                        continue
                    if len(room.players) < 2:
                        await _send_error(ws, "Precisa de pelo menos 2 jogadores.")
                        continue
                    room.round_num = 1
                    room.phase = "hands"
                    room.paused = False
                    _reset_round(room)
                    _build_round_order(room)
                    await _broadcast_state(room)
                    continue

                if mtype == "skip":
                    if room.phase not in ("hands", "guesses") or room.paused:
                        continue
                    _advance_turn(room)
                    await _broadcast_state(room)
                    continue

                # gameplay blocked if paused/over/lobby
                if room.paused:
                    continue

                if room.phase not in ("hands", "guesses"):
                    continue

                # must be your turn (turn-based)
                if not room.round_order:
                    continue
                turn_pid = room.round_order[room.turn_idx]
                if turn_pid != player.player_id:
                    continue

                if mtype == "hand" and room.phase == "hands":
                    try:
                        value = int(msg.get("value", 0))
                    except Exception:
                        value = 0
                    max_hand = min(3, player.balls_left)
                    if value < 0 or value > max_hand:
                        await _send_error(ws, f"Mão inválida (0..{max_hand}).")
                        continue

                    room.hands[player.player_id] = value
                    player.hand_submitted = True

                    # next turn or phase swap
                    if _all_submitted(room, "hands"):
                        room.phase = "guesses"
                        room.turn_idx = 0
                    else:
                        _advance_turn(room)

                    await _broadcast_state(room)
                    continue

                if mtype == "guess" and room.phase == "guesses":
                    try:
                        value = int(msg.get("value", 0))
                    except Exception:
                        value = 0

                    max_guess = sum(room.players[pid].balls_left for pid in room.round_order if pid in room.players and room.players[pid].alive)
                    if value < 0 or value > max_guess:
                        await _send_error(ws, f"Palpite inválido (0..{max_guess}).")
                        continue

                    if value in room.used_guesses:
                        await _send_error(ws, "Esse palpite já foi usado.")
                        continue

                    room.guesses[player.player_id] = value
                    room.used_guesses.append(value)
                    room.guesses_public.append({"name": player.name, "guess": value})
                    player.guess_submitted = True

                    if _all_submitted(room, "guesses"):
                        # reveal
                        total = sum(room.hands.get(pid, 0) for pid in room.round_order)
                        winners = _winner_names(room, total)

                        _apply_winners_lose_ball(room, winners)
                        game_over = _game_over(room)

                        result = {
                            "round_num": room.round_num,
                            "total": total,
                            "hands": {room.players[pid].name: room.hands.get(pid, 0) for pid in room.round_order if pid in room.players},
                            "guesses": {room.players[pid].name: room.guesses.get(pid, 0) for pid in room.round_order if pid in room.players},
                            "winner": winners[0] if len(winners) == 1 else None,
                            "winners": winners if len(winners) != 1 else [],
                        }

                        # broadcast reveal
                        payload = {"type": "reveal", "result": result, "game_over": game_over}
                        for p in list(room.players.values()):
                            if p.ws and p.connected:
                                await _safe_send(p.ws, payload)

                        if game_over:
                            room.phase = "over"
                        else:
                            # next round
                            room.round_num += 1
                            room.phase = "hands"
                            _reset_round(room)
                            _build_round_order(room)

                        await _broadcast_state(room)
                    else:
                        _advance_turn(room)
                        await _broadcast_state(room)

                    continue

    except WebSocketDisconnect:
        async with rooms_lock:
            room = rooms.get(room_id)
            if room and player.player_id in room.players:
                p = room.players[player.player_id]
                p.connected = False
                p.ws = None
                _ensure_host(room)
                await _broadcast_state(room)
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass