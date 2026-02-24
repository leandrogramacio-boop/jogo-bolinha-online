from __future__ import annotations

import os
import json
import uuid
import random
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


# =========================================================
# CONFIG
# =========================================================
APP_TITLE = "Jogo das Bolinhas (Online)"
MAX_PLAYERS = 10
START_BALLS = 3

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
INDEX_HTML = os.path.join(STATIC_DIR, "index.html")

app = FastAPI(title=APP_TITLE)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# =========================================================
# MODELOS
# =========================================================
@dataclass
class Player:
    player_id: str
    name: str
    key: str
    is_host: bool = False
    connected: bool = True
    alive: bool = True
    balls_left: int = START_BALLS

    hand_submitted: bool = False
    guess_submitted: bool = False
    current_hand: Optional[int] = None
    current_guess: Optional[int] = None


@dataclass
class Room:
    room_id: str
    players: List[Player] = field(default_factory=list)

    phase: str = "lobby"  # lobby | hands | guesses | reveal | over
    round_num: int = 0

    # turn control
    round_order: List[Dict[str, Any]] = field(default_factory=list)
    turn_index: int = 0
    turn_player_id: Optional[str] = None
    turn_player_name: Optional[str] = None

    used_guesses: List[int] = field(default_factory=list)
    max_guess: int = 0

    paused: bool = False

    # ✅ prêmio (host define)
    penalty_text: str = ""

    # ✅ chat
    chat_history: List[Dict[str, Any]] = field(default_factory=list)

    # WS connections
    sockets: Dict[str, WebSocket] = field(default_factory=dict)


ROOMS: Dict[str, Room] = {}


# =========================================================
# HELPERS
# =========================================================
def _make_room_id() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(6))


def _host(room: Room) -> Optional[Player]:
    for p in room.players:
        if p.is_host:
            return p
    return None


def _alive_players(room: Room) -> List[Player]:
    return [p for p in room.players if p.alive]


def _player_by_id(room: Room, pid: str) -> Optional[Player]:
    for p in room.players:
        if p.player_id == pid:
            return p
    return None


def _player_by_key(room: Room, key: str) -> Optional[Player]:
    for p in room.players:
        if p.key == key:
            return p
    return None


def _recalc_round_order(room: Room) -> None:
    alive = _alive_players(room)
    room.round_order = [{"player_id": p.player_id, "name": p.name} for p in alive]


def _set_turn(room: Room) -> None:
    if not room.round_order:
        room.turn_player_id = None
        room.turn_player_name = None
        return

    room.turn_index %= len(room.round_order)
    cur = room.round_order[room.turn_index]
    room.turn_player_id = cur["player_id"]
    room.turn_player_name = cur["name"]


def _compute_max_guess(room: Room) -> int:
    alive = _alive_players(room)
    return sum(min(START_BALLS, p.balls_left) for p in alive)


def _round_robin_shift(room: Room) -> None:
    # alterna o primeiro jogador a cada rodada
    if room.round_order:
        room.round_order = room.round_order[1:] + room.round_order[:1]
    room.turn_index = 0
    _set_turn(room)


# =========================================================
# STATE + BROADCAST
# =========================================================
def _base_state(room: Room) -> Dict[str, Any]:
    # ✅ Palpites públicos "rolando" (sempre no state)
    guesses_public = []
    for p in _alive_players(room):
        if p.guess_submitted and p.current_guess is not None:
            guesses_public.append({"name": p.name, "guess": int(p.current_guess)})

    return {
        "room_id": room.room_id,
        "phase": room.phase,
        "round_num": room.round_num,
        "host_player_id": (_host(room).player_id if _host(room) else None),
        "turn_player_id": room.turn_player_id,
        "turn_player_name": room.turn_player_name,
        "round_order": room.round_order,
        "used_guesses": room.used_guesses,
        "guesses_public": guesses_public,  # ✅ IMPORTANTE
        "max_guess": room.max_guess,
        "paused": room.paused,
        "penalty_text": room.penalty_text,
        "chat": room.chat_history[-50:],
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
            }
            for p in room.players
        ],
    }


async def _send(ws: WebSocket, payload: Dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _broadcast(room: Room, payload: Dict[str, Any]) -> None:
    dead = []
    for pid, ws in list(room.sockets.items()):
        try:
            await _send(ws, payload)
        except Exception:
            dead.append(pid)
    for pid in dead:
        room.sockets.pop(pid, None)


async def _broadcast_state(room: Room) -> None:
    await _broadcast(room, {"type": "state", "state": _base_state(room)})


# =========================================================
# GAME FLOW
# =========================================================
def _reset_round_flags(room: Room) -> None:
    for p in room.players:
        p.hand_submitted = False
        p.guess_submitted = False
        p.current_hand = None
        p.current_guess = None
    room.used_guesses = []


def _ensure_turn_is_valid(room: Room) -> None:
    if room.turn_player_id and _player_by_id(room, room.turn_player_id):
        return
    _set_turn(room)


def _advance_turn(room: Room) -> None:
    room.turn_index += 1
    if room.turn_index >= len(room.round_order):
        room.turn_index = 0
    _set_turn(room)


def _all_hands_submitted(room: Room) -> bool:
    alive = _alive_players(room)
    return bool(alive) and all(p.hand_submitted for p in alive)


def _all_guesses_submitted(room: Room) -> bool:
    alive = _alive_players(room)
    return bool(alive) and all(p.guess_submitted for p in alive)


def _start_game(room: Room) -> None:
    room.phase = "hands"
    room.round_num = 1
    _recalc_round_order(room)
    _round_robin_shift(room)
    _reset_round_flags(room)
    room.max_guess = _compute_max_guess(room)


def _restart_game(room: Room) -> None:
    for p in room.players:
        p.alive = True
        p.balls_left = START_BALLS
        p.hand_submitted = False
        p.guess_submitted = False
        p.current_hand = None
        p.current_guess = None
    room.phase = "lobby"
    room.round_num = 0
    room.used_guesses = []
    room.round_order = []
    room.turn_index = 0
    room.turn_player_id = None
    room.turn_player_name = None
    room.max_guess = 0
    room.paused = False


def _reveal(room: Room) -> Dict[str, Any]:
    hands = {}
    guesses = {}

    alive = _alive_players(room)
    for p in alive:
        hands[p.name] = int(p.current_hand or 0)
        guesses[p.name] = int(p.current_guess or 0)

    total = sum(hands.values())

    winner = None
    for p in alive:
        if (p.current_guess is not None) and int(p.current_guess) == total:
            winner = p
            break

    if winner:
        winner.balls_left -= 1
        if winner.balls_left <= 0:
            winner.balls_left = 0
            winner.alive = False

    # game over?
    alive_after = _alive_players(room)
    game_over = None
    if len(alive_after) <= 1 and room.phase != "lobby":
        room.phase = "over"
        loser = alive_after[0].name if alive_after else "?"
        game_over = {"loser": loser, "penalty_text": room.penalty_text}

    result = {
        "round_num": room.round_num,
        "total": total,
        "hands": hands,
        "guesses": guesses,
        "winner": (winner.name if winner else None),
    }
    return {"result": result, "game_over": game_over}


def _next_round(room: Room) -> None:
    room.round_num += 1
    room.phase = "hands"
    _recalc_round_order(room)
    _round_robin_shift(room)
    _reset_round_flags(room)
    room.max_guess = _compute_max_guess(room)


# =========================================================
# ROUTES
# =========================================================
@app.get("/")
async def root():
    return FileResponse(INDEX_HTML)


@app.get("/api/create-room")
async def api_create_room():
    rid = _make_room_id()
    ROOMS[rid] = Room(room_id=rid)
    return {"room_id": rid}


# =========================================================
# WS
# =========================================================
@app.websocket("/ws/{room_id}")
async def ws_room(ws: WebSocket, room_id: str, name: str = "Jogador", key: str = ""):
    await ws.accept()
    room_id = (room_id or "").strip().upper()
    name = (name or "Jogador").strip()[:24]

    if room_id not in ROOMS:
        ROOMS[room_id] = Room(room_id=room_id)
    room = ROOMS[room_id]

    # reconexão por key
    player: Optional[Player] = None
    if key:
        player = _player_by_key(room, key)
        if player:
            player.connected = True
            player.name = name

    if not player:
        if len(room.players) >= MAX_PLAYERS:
            await _send(ws, {"type": "error", "message": "Sala cheia."})
            await ws.close()
            return

        pid = uuid.uuid4().hex[:10]
        pkey = uuid.uuid4().hex
        player = Player(player_id=pid, name=name, key=pkey)
        if not _host(room):
            player.is_host = True
        room.players.append(player)

    room.sockets[player.player_id] = ws

    await _send(ws, {"type": "joined", "player_id": player.player_id, "room_id": room.room_id, "player_key": player.key})
    await _broadcast_state(room)

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "ping":
                await _send(ws, {"type": "pong"})
                continue

            # pausa bloqueia ações do jogo (mas deixa chat/penalty)
            if room.paused and mtype in ("start", "hand", "guess", "skip", "restart"):
                await _send(ws, {"type": "error", "message": "Jogo pausado pelo host."})
                continue

            if mtype == "start":
                if not player.is_host:
                    await _send(ws, {"type": "error", "message": "Somente host pode iniciar."})
                    continue
                if room.phase != "lobby":
                    continue
                if len(_alive_players(room)) < 2:
                    await _send(ws, {"type": "error", "message": "Precisa de pelo menos 2 jogadores."})
                    continue
                _start_game(room)
                await _broadcast_state(room)
                continue

            if mtype == "restart":
                if not player.is_host:
                    await _send(ws, {"type": "error", "message": "Somente host pode reiniciar."})
                    continue
                _restart_game(room)
                await _broadcast_state(room)
                continue

            if mtype == "skip":
                if not player.is_host:
                    await _send(ws, {"type": "error", "message": "Somente host pode pular vez."})
                    continue
                if room.phase not in ("hands", "guesses"):
                    continue
                _advance_turn(room)
                await _broadcast_state(room)
                continue

            if mtype == "pause":
                if not player.is_host:
                    await _send(ws, {"type": "error", "message": "Somente host pode pausar."})
                    continue
                room.paused = True
                await _broadcast_state(room)
                continue

            if mtype == "resume":
                if not player.is_host:
                    await _send(ws, {"type": "error", "message": "Somente host pode retomar."})
                    continue
                room.paused = False
                await _broadcast_state(room)
                continue

            if mtype == "set_penalty":
                if not player.is_host:
                    await _send(ws, {"type": "error", "message": "Somente host pode definir prêmio."})
                    continue
                txt = (msg.get("value") or "").strip()
                room.penalty_text = txt[:80]
                await _broadcast_state(room)
                continue

            if mtype == "chat":
                txt = (msg.get("text") or "").strip()
                if not txt:
                    continue
                room.chat_history.append({"name": player.name, "text": txt[:220]})
                await _broadcast_state(room)
                continue

            if mtype == "hand":
                if room.phase != "hands":
                    continue
                _ensure_turn_is_valid(room)
                if room.turn_player_id != player.player_id:
                    await _send(ws, {"type": "error", "message": "Não é sua vez."})
                    continue
                if player.hand_submitted:
                    continue
                v = int(msg.get("value", 0))
                v = max(0, min(START_BALLS, v, player.balls_left))
                player.current_hand = v
                player.hand_submitted = True
                _advance_turn(room)

                if _all_hands_submitted(room):
                    room.phase = "guesses"
                    room.used_guesses = []
                    room.turn_index = 0
                    _set_turn(room)

                await _broadcast_state(room)
                continue

            if mtype == "guess":
                if room.phase != "guesses":
                    continue
                _ensure_turn_is_valid(room)
                if room.turn_player_id != player.player_id:
                    await _send(ws, {"type": "error", "message": "Não é sua vez."})
                    continue
                if player.guess_submitted:
                    continue
                v = int(msg.get("value", 0))
                if v in room.used_guesses:
                    await _send(ws, {"type": "error", "message": "Palpite já usado."})
                    continue
                v = max(0, min(room.max_guess, v))
                player.current_guess = v
                player.guess_submitted = True
                room.used_guesses.append(v)
                _advance_turn(room)

                if _all_guesses_submitted(room):
                    room.phase = "reveal"
                    payload = _reveal(room)

                    await _broadcast(room, {"type": "reveal", **payload})
                    await _broadcast_state(room)

                    if room.phase != "over":
                        _next_round(room)
                        await _broadcast_state(room)

                else:
                    await _broadcast_state(room)
                continue

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        # desconecta
        player.connected = False
        room.sockets.pop(player.player_id, None)
        await _broadcast_state(room)