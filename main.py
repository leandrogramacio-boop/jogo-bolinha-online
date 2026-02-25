from __future__ import annotations

import asyncio
import secrets
import string
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# =========================
# App / Static
# =========================
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def home():
    return FileResponse("static/index.html")


# =========================
# Modelos
# =========================
def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_room_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def _new_key() -> str:
    return secrets.token_urlsafe(18)


@dataclass
class Player:
    player_id: str
    key: str
    name: str

    balls_left: int = 3
    alive: bool = True
    connected: bool = False
    is_host: bool = False

    hand_submitted: bool = False
    guess_submitted: bool = False

    reaction: str = ""  # 😊 😭 😡
    last_hand: Optional[int] = None  # mão escolhida na rodada atual (privado no state)

    ws: Optional[WebSocket] = None


@dataclass
class Room:
    room_id: str
    players: Dict[str, Player] = field(default_factory=dict)

    host_player_id: Optional[str] = None

    phase: str = "lobby"  # lobby, hands, guesses, reveal, over
    round_num: int = 0

    round_order: List[str] = field(default_factory=list)  # player_id
    turn_idx: int = 0

    max_guess: int = 0
    used_guesses: List[int] = field(default_factory=list)
    hands: Dict[str, int] = field(default_factory=dict)   # player_id -> hand
    guesses: Dict[str, int] = field(default_factory=dict) # player_id -> guess

    starter_offset: int = 0

    paused: bool = False
    prize_text: str = ""

    chat_log: List[Dict[str, Any]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


rooms: Dict[str, Room] = {}


# =========================
# Helpers WS
# =========================
async def _safe_send(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_json(payload)
    except Exception:
        pass


async def _send_error(ws: WebSocket, message: str) -> None:
    await _safe_send(ws, {"type": "error", "message": message})


def _alive_players(room: Room) -> List[Player]:
    return [p for p in room.players.values() if p.alive]


def _alive_ids(room: Room) -> List[str]:
    return [p.player_id for p in _alive_players(room)]


def _connected_alive_ids(room: Room) -> List[str]:
    out = []
    for p in _alive_players(room):
        if p.connected and p.ws is not None:
            out.append(p.player_id)
    return out


def _turn_player_id(room: Room) -> Optional[str]:
    if not room.round_order:
        return None
    if room.turn_idx < 0 or room.turn_idx >= len(room.round_order):
        return None
    return room.round_order[room.turn_idx]


def _turn_player_name(room: Room) -> Optional[str]:
    pid = _turn_player_id(room)
    if not pid:
        return None
    p = room.players.get(pid)
    return p.name if p else None


def _round_order_public(room: Room) -> List[dict]:
    out = []
    for pid in room.round_order:
        p = room.players.get(pid)
        if p:
            out.append({"player_id": p.player_id, "name": p.name})
    return out


def _guesses_public(room: Room) -> List[dict]:
    # Em ordem de envio (aproximado): usa round_order e pega os que já chutaram
    out = []
    for pid in room.round_order:
        if pid in room.guesses:
            p = room.players.get(pid)
            if p:
                out.append({"name": p.name, "guess": room.guesses[pid]})
    return out


def _build_state(room: Room, for_player_id: Optional[str]) -> dict:
    players_list = []
    for p in room.players.values():
        players_list.append({
            "player_id": p.player_id,
            "name": p.name,
            "balls_left": p.balls_left,
            "alive": p.alive,
            "connected": p.connected,
            "is_host": p.is_host,
            "hand_submitted": p.hand_submitted,
            "guess_submitted": p.guess_submitted,
            "reaction": p.reaction or ""
        })

    your_hand = None
    if for_player_id and for_player_id in room.players:
        your_hand = room.players[for_player_id].last_hand

    return {
        "room_id": room.room_id,
        "phase": room.phase,
        "round_num": room.round_num,
        "host_player_id": room.host_player_id,
        "turn_player_id": _turn_player_id(room),
        "turn_player_name": _turn_player_name(room),
        "round_order": _round_order_public(room),
        "max_guess": room.max_guess,
        "used_guesses": room.used_guesses,
        "guesses_public": _guesses_public(room),
        "paused": room.paused,
        "prize_text": room.prize_text,
        "players": players_list,
        "your_hand": your_hand,  # ✅ privado
    }


async def _broadcast_state(room: Room) -> None:
    # manda state personalizado (com your_hand)
    for p in room.players.values():
        if p.ws and p.connected:
            await _safe_send(p.ws, {"type": "state", "state": _build_state(room, p.player_id)})


async def _broadcast_event(room: Room, payload: dict) -> None:
    for p in room.players.values():
        if p.ws and p.connected:
            await _safe_send(p.ws, payload)


def _ensure_host(room: Room) -> None:
    # Se não houver host ou host morreu, escolhe o primeiro alive
    if room.host_player_id and room.host_player_id in room.players:
        hp = room.players[room.host_player_id]
        if hp.alive:
            return

    alive = _alive_players(room)
    if not alive:
        room.host_player_id = None
        return

    room.host_player_id = alive[0].player_id
    for p in room.players.values():
        p.is_host = (p.player_id == room.host_player_id)


def _reset_round_flags(room: Room) -> None:
    room.hands.clear()
    room.guesses.clear()
    room.used_guesses.clear()
    for p in room.players.values():
        p.hand_submitted = False
        p.guess_submitted = False
        p.last_hand = None


def _compute_max_guess(room: Room) -> int:
    # máximo possível nesta rodada = soma de min(3, balls_left) dos alive
    total = 0
    for p in _alive_players(room):
        total += min(3, p.balls_left)
    return total


def _build_round_order(room: Room) -> None:
    alive_ids = _alive_ids(room)
    if not alive_ids:
        room.round_order = []
        room.turn_idx = 0
        return

    off = room.starter_offset % len(alive_ids)
    room.round_order = alive_ids[off:] + alive_ids[:off]
    room.turn_idx = 0


def _advance_turn(room: Room) -> None:
    if not room.round_order:
        return
    room.turn_idx = (room.turn_idx + 1) % len(room.round_order)


def _all_alive_submitted(room: Room, kind: str) -> bool:
    # kind: "hand" or "guess"
    for pid in room.round_order:
        p = room.players.get(pid)
        if not p or not p.alive:
            continue
        if kind == "hand" and not p.hand_submitted:
            return False
        if kind == "guess" and not p.guess_submitted:
            return False
    return True


def _start_game(room: Room) -> None:
    _ensure_host(room)
    _reset_round_flags(room)
    room.round_num = 1
    room.phase = "hands"
    room.paused = False
    room.max_guess = _compute_max_guess(room)
    _build_round_order(room)


def _restart_game(room: Room) -> None:
    # mantém jogadores, reseta status do jogo
    for p in room.players.values():
        p.balls_left = 3
        p.alive = True
        p.hand_submitted = False
        p.guess_submitted = False
        p.last_hand = None
        p.reaction = p.reaction  # mantém reação se quiser

    room.phase = "lobby"
    room.round_num = 0
    room.starter_offset = 0
    room.paused = False
    room.max_guess = 0
    room.round_order = []
    room.turn_idx = 0
    room.hands.clear()
    room.guesses.clear()
    room.used_guesses.clear()
    _ensure_host(room)


def _next_round(room: Room) -> None:
    _reset_round_flags(room)
    room.round_num += 1
    room.phase = "hands"
    room.starter_offset += 1
    room.max_guess = _compute_max_guess(room)
    _build_round_order(room)


def _game_over_if_needed(room: Room) -> Optional[dict]:
    alive = _alive_players(room)
    if len(alive) == 1:
        # última pessoa viva é o perdedor
        return {"loser": alive[0].name}
    return None


# =========================
# API
# =========================
@app.get("/api/create-room")
def create_room():
    # cria sala vazia
    for _ in range(10):
        rid = _new_room_id()
        if rid not in rooms:
            rooms[rid] = Room(room_id=rid)
            return JSONResponse({"room_id": rid})
    rid = _new_room_id()
    rooms[rid] = Room(room_id=rid)
    return JSONResponse({"room_id": rid})


# =========================
# WebSocket
# =========================
@app.websocket("/ws/{room_id}")
async def ws_room(ws: WebSocket, room_id: str):
    await ws.accept()

    name = (ws.query_params.get("name") or "Jogador").strip()[:24]
    key = (ws.query_params.get("key") or "").strip()

    room_id = (room_id or "").strip().upper()
    if not room_id:
        await _send_error(ws, "Sala inválida.")
        await ws.close()
        return

    # cria sala se não existir
    if room_id not in rooms:
        rooms[room_id] = Room(room_id=room_id)

    room = rooms[room_id]

    async with room.lock:
        # reconexão por key
        player: Optional[Player] = None
        if key:
            for p in room.players.values():
                if p.key == key:
                    player = p
                    break

        if player is None:
            pid = uuid.uuid4().hex[:10]
            pkey = _new_key()
            player = Player(player_id=pid, key=pkey, name=name)
            room.players[pid] = player

        # atualiza conexão / nome
        player.name = name
        player.ws = ws
        player.connected = True

        # define host se for o primeiro (ou se não tem)
        if room.host_player_id is None:
            room.host_player_id = player.player_id
        _ensure_host(room)

        await _safe_send(ws, {
            "type": "joined",
            "player_id": player.player_id,
            "room_id": room.room_id,
            "player_key": player.key
        })

        # manda estado inicial
        await _broadcast_state(room)

        # manda backlog pequeno do chat pro recém-chegado
        for m in room.chat_log[-40:]:
            await _safe_send(ws, {"type": "chat", "msg": m})

    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue

            mtype = (msg.get("type") or "").strip()

            async with room.lock:
                # pode ter sido removido
                if player.player_id not in room.players:
                    await _send_error(ws, "Você não está mais na sala.")
                    await ws.close()
                    return

                # ===== keepalive =====
                if mtype == "ping":
                    await _safe_send(ws, {"type": "pong"})
                    continue

                # ===== chat =====
                if mtype == "chat":
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    text = text[:400]
                    payload = {
                        "id": uuid.uuid4().hex[:10],
                        "ts": _now_ms(),
                        "name": player.name,
                        "text": text,
                    }
                    room.chat_log.append(payload)
                    room.chat_log = room.chat_log[-200:]
                    await _broadcast_event(room, {"type": "chat", "msg": payload})
                    continue

                # ===== reação =====
                if mtype == "react":
                    emoji = (msg.get("emoji") or "").strip()
                    if emoji not in ("😊", "😭", "😡", ""):
                        continue
                    player.reaction = emoji
                    await _broadcast_state(room)
                    continue

                # ===== host-only: set prize =====
                if mtype == "set_prize":
                    if room.host_player_id != player.player_id:
                        await _send_error(ws, "Só o host pode definir o prêmio.")
                        continue
                    txt = (msg.get("text") or "").strip()
                    room.prize_text = txt[:80]
                    await _broadcast_state(room)
                    continue

                # ===== host-only: pause =====
                if mtype == "pause":
                    if room.host_player_id != player.player_id:
                        await _send_error(ws, "Só o host pode pausar.")
                        continue
                    room.paused = not room.paused
                    await _broadcast_state(room)
                    continue

                # se pausado, bloqueia ações do jogo (mas mantém chat/react/ping)
                if room.paused and mtype in ("hand", "guess", "start", "restart", "skip"):
                    await _send_error(ws, "Jogo está pausado.")
                    continue

                # ===== host-only: start =====
                if mtype == "start":
                    if room.host_player_id != player.player_id:
                        await _send_error(ws, "Só o host pode iniciar.")
                        continue
                    if room.phase != "lobby":
                        continue
                    if len(_alive_players(room)) < 2:
                        await _send_error(ws, "Precisa de pelo menos 2 jogadores.")
                        continue
                    _start_game(room)
                    await _broadcast_state(room)
                    continue

                # ===== host-only: restart =====
                if mtype == "restart":
                    if room.host_player_id != player.player_id:
                        await _send_error(ws, "Só o host pode reiniciar.")
                        continue
                    _restart_game(room)
                    await _broadcast_state(room)
                    continue

                # ===== host-only: skip =====
                if mtype == "skip":
                    if room.host_player_id != player.player_id:
                        await _send_error(ws, "Só o host pode pular.")
                        continue
                    if room.phase not in ("hands", "guesses"):
                        continue
                    _advance_turn(room)
                    await _broadcast_state(room)
                    continue

                # ===== hand =====
                if mtype == "hand":
                    if room.phase != "hands":
                        continue
                    if not player.alive:
                        continue
                    if player.hand_submitted:
                        continue
                    if _turn_player_id(room) != player.player_id:
                        await _send_error(ws, "Não é sua vez.")
                        continue

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
                    player.last_hand = value  # ✅ privado

                    if _all_alive_submitted(room, "hand"):
                        # vai pra guesses
                        room.phase = "guesses"
                        room.turn_idx = 0
                        room.used_guesses.clear()
                        room.guesses.clear()
                        for pid in room.round_order:
                            p = room.players.get(pid)
                            if p and p.alive:
                                p.guess_submitted = False
                        await _broadcast_state(room)
                    else:
                        _advance_turn(room)
                        await _broadcast_state(room)
                    continue

                # ===== guess =====
                if mtype == "guess":
                    if room.phase != "guesses":
                        continue
                    if not player.alive:
                        continue
                    if player.guess_submitted:
                        continue
                    if _turn_player_id(room) != player.player_id:
                        await _send_error(ws, "Não é sua vez.")
                        continue

                    try:
                        value = int(msg.get("value", 0))
                    except Exception:
                        value = 0

                    if value < 0 or value > (room.max_guess or 0):
                        await _send_error(ws, "Palpite inválido.")
                        continue
                    if value in room.used_guesses:
                        await _send_error(ws, "Esse palpite já foi usado.")
                        continue

                    room.guesses[player.player_id] = value
                    room.used_guesses.append(value)
                    player.guess_submitted = True

                    if _all_alive_submitted(room, "guess"):
                        # reveal
                        room.phase = "reveal"
                        total = sum(room.hands.get(pid, 0) for pid in room.round_order)

                        winners: List[str] = []
                        for pid, g in room.guesses.items():
                            if g == total:
                                winners.append(pid)

                        # cada winner perde 1 bolinha
                        for pid in winners:
                            p = room.players.get(pid)
                            if not p or not p.alive:
                                continue
                            p.balls_left = max(0, p.balls_left - 1)
                            if p.balls_left == 0:
                                p.alive = False

                        _ensure_host(room)

                        # monta reveal no formato que seu front espera
                        hands_by_name = {}
                        guesses_by_name = {}
                        for pid in room.round_order:
                            p = room.players.get(pid)
                            if not p:
                                continue
                            hands_by_name[p.name] = room.hands.get(pid, 0)
                            if pid in room.guesses:
                                guesses_by_name[p.name] = room.guesses[pid]

                        winner_name = None
                        if len(winners) == 1:
                            wp = room.players.get(winners[0])
                            winner_name = wp.name if wp else None

                        winners_names = []
                        for pid in winners:
                            wp = room.players.get(pid)
                            if wp:
                                winners_names.append(wp.name)

                        game_over = _game_over_if_needed(room)
                        reveal_payload = {
                            "type": "reveal",
                            "result": {
                                "round_num": room.round_num,
                                "total": total,
                                "hands": hands_by_name,
                                "guesses": guesses_by_name,
                                "winner": winner_name,
                                "winners": winners_names,
                            },
                            "game_over": game_over
                        }

                        await _broadcast_event(room, reveal_payload)

                        # avança: ou acaba, ou próxima rodada
                        if game_over:
                            room.phase = "over"
                            await _broadcast_state(room)
                        else:
                            _next_round(room)
                            await _broadcast_state(room)
                    else:
                        _advance_turn(room)
                        await _broadcast_state(room)
                    continue

                # desconhecido
                # (ignora silenciosamente)
                continue

    except WebSocketDisconnect:
        pass
    finally:
        async with room.lock:
            # marca desconectado
            if player.player_id in room.players:
                player.connected = False
                player.ws = None

                # se host saiu, promove outro (só se quiser)
                if room.host_player_id == player.player_id:
                    _ensure_host(room)

                await _broadcast_state(room)