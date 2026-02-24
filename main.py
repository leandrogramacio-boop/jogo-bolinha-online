from __future__ import annotations

import asyncio
import json
import secrets
import string
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# =========================
# App / Static
# =========================
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return FileResponse("static/index.html")


# =========================
# Game Model
# =========================
def _room_id(n: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _player_id() -> str:
    return secrets.token_hex(6)


def _player_key() -> str:
    return secrets.token_hex(12)


@dataclass
class Player:
    player_id: str
    name: str
    key: str
    is_host: bool = False
    connected: bool = True
    alive: bool = True
    balls_left: int = 3

    hand_submitted: bool = False
    guess_submitted: bool = False

    # valores da rodada (servidor)
    current_hand: Optional[int] = None
    current_guess: Optional[int] = None

    # para “cada um ver a sua mão” (último hand enviado por ele)
    last_hand_sent: Optional[int] = None


@dataclass
class Room:
    room_id: str
    players: List[Player] = field(default_factory=list)

    phase: str = "lobby"  # lobby | hands | guesses | reveal | over
    round_num: int = 0

    turn_player_id: Optional[str] = None
    turn_player_name: Optional[str] = None

    # round-robin: índice do primeiro jogador da rodada
    starter_index: int = 0

    # ordem da rodada (snapshot)
    round_order: List[Dict[str, Any]] = field(default_factory=list)

    used_guesses: List[int] = field(default_factory=list)
    max_guess: int = 0

    paused: bool = False
    penalty_text: str = ""

    # chat
    chat_history: List[Dict[str, Any]] = field(default_factory=list)  # [{name,text,ts}]

    # conexões WS: websocket -> player_id
    sockets: Dict[WebSocket, str] = field(default_factory=dict)

    # trava leve por sala
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


ROOMS: Dict[str, Room] = {}


def _now_ts() -> int:
    # timestamp simples (segundos)
    return int(asyncio.get_event_loop().time())


def _find_player(room: Room, pid: str) -> Optional[Player]:
    for p in room.players:
        if p.player_id == pid:
            return p
    return None


def _host(room: Room) -> Optional[Player]:
    for p in room.players:
        if p.is_host:
            return p
    return None


def _alive_players(room: Room) -> List[Player]:
    return [p for p in room.players if p.alive]


def _rebuild_round_order(room: Room) -> None:
    alive = _alive_players(room)
    if not alive:
        room.round_order = []
        return

    # round-robin starter
    if room.starter_index >= len(alive):
        room.starter_index = 0

    ordered = alive[room.starter_index :] + alive[: room.starter_index]
    room.round_order = [{"player_id": p.player_id, "name": p.name} for p in ordered]


def _set_turn(room: Room, player_id: Optional[str]) -> None:
    room.turn_player_id = player_id
    pl = _find_player(room, player_id) if player_id else None
    room.turn_player_name = pl.name if pl else None


def _next_turn_in_order(room: Room, start_after_pid: Optional[str]) -> Optional[str]:
    """Given current order, return next alive player's id after start_after_pid, or first if None."""
    order = room.round_order or []
    if not order:
        return None
    ids = [x["player_id"] for x in order]

    if start_after_pid is None or start_after_pid not in ids:
        return ids[0]

    i = ids.index(start_after_pid)
    for j in range(i + 1, len(ids)):
        pid = ids[j]
        p = _find_player(room, pid)
        if p and p.alive:
            return pid
    return None


def _all_hands_done(room: Room) -> bool:
    for p in _alive_players(room):
        if not p.hand_submitted:
            return False
    return True


def _all_guesses_done(room: Room) -> bool:
    for p in _alive_players(room):
        if not p.guess_submitted:
            return False
    return True


def _compute_max_guess(room: Room) -> int:
    # max total possível = soma das bolinhas que cada vivo ainda tem (cap 3)
    alive = _alive_players(room)
    return sum(min(3, max(0, p.balls_left)) for p in alive)


def _start_round(room: Room) -> None:
    room.round_num += 1
    room.used_guesses = []
    room.max_guess = _compute_max_guess(room)

    # reset flags/rodada
    for p in room.players:
        p.hand_submitted = False
        p.guess_submitted = False
        p.current_hand = None
        p.current_guess = None

    room.phase = "hands"
    _rebuild_round_order(room)
    _set_turn(room, room.round_order[0]["player_id"] if room.round_order else None)


def _advance_starter(room: Room) -> None:
    alive = _alive_players(room)
    if not alive:
        room.starter_index = 0
        return
    room.starter_index = (room.starter_index + 1) % len(alive)


def _finish_reveal_and_check_end(room: Room, winner_name: Optional[str]) -> Optional[Dict[str, Any]]:
    # Quem acerta perde 1 bolinha
    if winner_name:
        for p in room.players:
            if p.alive and p.name == winner_name:
                p.balls_left = max(0, p.balls_left - 1)
                if p.balls_left == 0:
                    p.alive = False
                break

    alive = _alive_players(room)
    if len(alive) <= 1:
        room.phase = "over"
        # último sobrevivente perde
        loser = alive[0].name if alive else "?"
        return {"loser": loser, "penalty": room.penalty_text}

    # próxima rodada
    _advance_starter(room)
    _start_round(room)
    return None


def _base_state(room: Room) -> Dict[str, Any]:
    # estado "comum" (o que todo mundo pode ver)
    return {
        "room_id": room.room_id,
        "phase": room.phase,
        "round_num": room.round_num,
        "host_player_id": (_host(room).player_id if _host(room) else None),
        "turn_player_id": room.turn_player_id,
        "turn_player_name": room.turn_player_name,
        "round_order": room.round_order,
        "used_guesses": room.used_guesses,
        "max_guess": room.max_guess,
        "paused": room.paused,
        "penalty_text": room.penalty_text,
        "chat": room.chat_history[-50:],  # últimos 50
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
    await ws.send_text(json.dumps(payload))


async def _broadcast_state(room: Room) -> None:
    """Envia state para cada websocket com campo extra: my_last_hand."""
    base = _base_state(room)

    for ws, pid in list(room.sockets.items()):
        p = _find_player(room, pid)
        st = dict(base)
        st["my_last_hand"] = (p.last_hand_sent if p else None)
        try:
            await _send(ws, {"type": "state", "state": st})
        except Exception:
            # socket morreu
            room.sockets.pop(ws, None)


async def _broadcast_chat(room: Room, msg: Dict[str, Any]) -> None:
    # opcional: evento imediato de chat (além do state)
    for ws in list(room.sockets.keys()):
        try:
            await _send(ws, {"type": "chat", "message": msg})
        except Exception:
            room.sockets.pop(ws, None)


# =========================
# API
# =========================
@app.get("/api/create-room")
def create_room():
    rid = _room_id()
    ROOMS[rid] = Room(room_id=rid)
    return {"room_id": rid}


# =========================
# WebSocket
# =========================
@app.websocket("/ws/{room_id}")
async def ws_room(websocket: WebSocket, room_id: str, name: str = "Jogador", key: str = ""):
    room_id = (room_id or "").strip().upper()
    name = (name or "Jogador").strip()

    if room_id not in ROOMS:
        # cria sob demanda (opcional)
        ROOMS[room_id] = Room(room_id=room_id)

    room = ROOMS[room_id]

    await websocket.accept()

    async with room.lock:
        # reconexão por key
        player = None
        if key:
            for p in room.players:
                if p.key == key:
                    player = p
                    break

        if player:
            player.connected = True
            player.name = name or player.name
        else:
            pid = _player_id()
            pkey = _player_key()
            player = Player(player_id=pid, name=name, key=pkey, is_host=False)
            room.players.append(player)

            # se é o primeiro, vira host
            if len(room.players) == 1:
                player.is_host = True

        # registra socket
        room.sockets[websocket] = player.player_id

        # joined
        await _send(
            websocket,
            {"type": "joined", "player_id": player.player_id, "room_id": room.room_id, "player_key": player.key},
        )

        # manda state inicial
        await _broadcast_state(room)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            mtype = msg.get("type")
            async with room.lock:
                pid = room.sockets.get(websocket)
                me = _find_player(room, pid) if pid else None
                if not me:
                    continue

                # ============ keepalive ============
                if mtype == "ping":
                    await _send(websocket, {"type": "pong"})
                    continue

                # ============ chat ============
                if mtype == "chat":
                    text = str(msg.get("text", "")).strip()
                    if text:
                        item = {"name": me.name, "text": text[:400], "ts": _now_ts()}
                        room.chat_history.append(item)
                        # evento imediato (e depois state)
                        await _broadcast_chat(room, item)
                        await _broadcast_state(room)
                    continue

                # ============ host-only ============
                if mtype in ("start", "restart", "skip", "kick", "pause", "set_penalty") and not me.is_host:
                    await _send(websocket, {"type": "error", "message": "Apenas o host pode fazer isso."})
                    continue

                # ============ pause ============
                if mtype == "pause":
                    # alterna pause
                    room.paused = not room.paused
                    await _broadcast_state(room)
                    continue

                # bloqueia ações de jogo quando pausado (mas permite set_penalty, chat e restart)
                if room.paused and mtype in ("start", "hand", "guess", "skip"):
                    await _send(websocket, {"type": "error", "message": "Jogo está pausado."})
                    continue

                # ============ penalty ============
                if mtype == "set_penalty":
                    room.penalty_text = str(msg.get("text", "")).strip()[:120]
                    await _broadcast_state(room)
                    continue

                # ============ kick ============
                if mtype == "kick":
                    target = str(msg.get("target_id", ""))
                    tp = _find_player(room, target)
                    if tp and tp.player_id != me.player_id:
                        # derruba conexões do alvo
                        for ws2, pid2 in list(room.sockets.items()):
                            if pid2 == tp.player_id:
                                try:
                                    await _send(ws2, {"type": "kicked", "message": "Você foi removido pelo host."})
                                except Exception:
                                    pass
                                try:
                                    await ws2.close()
                                except Exception:
                                    pass
                                room.sockets.pop(ws2, None)
                        tp.connected = False
                        # opcional: remove do jogo
                        tp.alive = False
                        await _broadcast_state(room)
                    continue

                # ============ start/restart ============
                if mtype == "start":
                    if room.phase != "lobby":
                        continue
                    if len(_alive_players(room)) < 2:
                        await _send(websocket, {"type": "error", "message": "Precisa de pelo menos 2 jogadores."})
                        continue
                    _start_round(room)
                    await _broadcast_state(room)
                    continue

                if mtype == "restart":
                    # reset geral, mantém players
                    room.phase = "lobby"
                    room.round_num = 0
                    room.starter_index = 0
                    room.round_order = []
                    room.used_guesses = []
                    room.max_guess = 0
                    room.turn_player_id = None
                    room.turn_player_name = None
                    room.paused = False

                    for p in room.players:
                        p.alive = True
                        p.balls_left = 3
                        p.hand_submitted = False
                        p.guess_submitted = False
                        p.current_hand = None
                        p.current_guess = None
                        p.last_hand_sent = None

                    await _broadcast_state(room)
                    continue

                # ============ skip ============
                if mtype == "skip":
                    if room.phase not in ("hands", "guesses"):
                        continue
                    # pula para próximo jogador na ordem
                    nxt = _next_turn_in_order(room, room.turn_player_id)
                    _set_turn(room, nxt)
                    await _broadcast_state(room)
                    continue

                # ============ hand ============
                if mtype == "hand":
                    if room.phase != "hands":
                        continue
                    if room.turn_player_id != me.player_id:
                        await _send(websocket, {"type": "error", "message": "Não é sua vez."})
                        continue
                    if me.hand_submitted:
                        continue

                    try:
                        v = int(msg.get("value", 0))
                    except Exception:
                        v = 0
                    v = max(0, min(3, v))
                    v = min(v, max(0, me.balls_left))  # não pode mandar mais que estoque

                    me.current_hand = v
                    me.hand_submitted = True
                    me.last_hand_sent = v  # 👈 cada um vê a própria mão enviada

                    # avança turno
                    nxt = _next_turn_in_order(room, room.turn_player_id)
                    _set_turn(room, nxt)

                    # se todos enviaram, muda fase
                    if _all_hands_done(room):
                        room.phase = "guesses"
                        room.used_guesses = []
                        room.max_guess = _compute_max_guess(room)
                        _set_turn(room, room.round_order[0]["player_id"] if room.round_order else None)

                    await _broadcast_state(room)
                    continue

                # ============ guess ============
                if mtype == "guess":
                    if room.phase != "guesses":
                        continue
                    if room.turn_player_id != me.player_id:
                        await _send(websocket, {"type": "error", "message": "Não é sua vez."})
                        continue
                    if me.guess_submitted:
                        continue

                    try:
                        g = int(msg.get("value", 0))
                    except Exception:
                        g = 0

                    if g < 0 or g > room.max_guess:
                        await _send(websocket, {"type": "error", "message": f"Palpite inválido (0..{room.max_guess})."})
                        continue
                    if g in room.used_guesses:
                        await _send(websocket, {"type": "error", "message": "Esse palpite já foi usado."})
                        continue

                    me.current_guess = g
                    me.guess_submitted = True
                    room.used_guesses.append(g)

                    # avança turno
                    nxt = _next_turn_in_order(room, room.turn_player_id)
                    _set_turn(room, nxt)

                    # se todos deram palpite, REVEAL
                    if _all_guesses_done(room):
                        room.phase = "reveal"

                        hands = {p.name: int(p.current_hand or 0) for p in _alive_players(room)}
                        guesses = {p.name: int(p.current_guess or 0) for p in _alive_players(room)}
                        total = sum(hands.values())

                        winner_name = None
                        for nm, gv in guesses.items():
                            if gv == total:
                                winner_name = nm
                                break

                        result = {
                            "round_num": room.round_num,
                            "total": total,
                            "winner": winner_name,
                            "hands": hands,
                            "guesses": guesses,
                        }

                        game_over = _finish_reveal_and_check_end(room, winner_name)

                        # envia reveal
                        for ws2 in list(room.sockets.keys()):
                            try:
                                await _send(ws2, {"type": "reveal", "result": result, "game_over": game_over})
                            except Exception:
                                room.sockets.pop(ws2, None)

                        # e atualiza state (inclui balls_left pós redução)
                        await _broadcast_state(room)
                        continue

                    await _broadcast_state(room)
                    continue

    except WebSocketDisconnect:
        pass
    finally:
        async with room.lock:
            pid = room.sockets.pop(websocket, None)
            if pid:
                p = _find_player(room, pid)
                if p:
                    p.connected = False

                # se host caiu, transfere host pro primeiro conectado vivo
                h = _host(room)
                if h and h.player_id == pid:
                    h.is_host = False
                    for cand in room.players:
                        if cand.connected and cand.alive:
                            cand.is_host = True
                            break

            try:
                await _broadcast_state(room)
            except Exception:
                pass