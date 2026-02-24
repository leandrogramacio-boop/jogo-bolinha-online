from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


# =========================
# CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

MAX_PLAYERS_PER_ROOM = 10
STARTING_BALLS = 3

DISCONNECTED_PURGE_SECONDS = 15 * 60
ROOM_IDLE_PURGE_SECONDS = 12 * 60 * 60
CLEANUP_EVERY_SECONDS = 5 * 60


# =========================
# HELPERS
# =========================
def now_ts() -> float:
    return time.time()


def gen_room_id() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def gen_player_id() -> str:
    return secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:10]


def gen_player_key() -> str:
    return secrets.token_urlsafe(18)


async def safe_send(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


# =========================
# MODELOS
# =========================
@dataclass
class Player:
    player_id: str
    key: str
    name: str
    balls_left: int = STARTING_BALLS
    ws: Optional[WebSocket] = None
    connected: bool = False
    disconnected_at: Optional[float] = None

    hand_submitted: bool = False
    guess_submitted: bool = False

    @property
    def alive(self) -> bool:
        return self.balls_left > 0


@dataclass
class Room:
    room_id: str
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)

    host_player_id: Optional[str] = None

    phase: str = "lobby"  # lobby -> hands -> guesses -> reveal -> over
    round_num: int = 0

    players: Dict[str, Player] = field(default_factory=dict)

    # ordem fixa (entrada)
    base_order: List[str] = field(default_factory=list)

    # ordem desta rodada (rotacionada)
    starter_pid: Optional[str] = None
    round_order: List[str] = field(default_factory=list)

    # controle de "vez"
    turn_player_id: Optional[str] = None

    # dados da rodada
    hands: Dict[str, int] = field(default_factory=dict)
    guesses: Dict[str, int] = field(default_factory=dict)
    used_guesses: Set[int] = field(default_factory=set)

    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def touch(self) -> None:
        self.updated_at = now_ts()

    def alive_players(self) -> Dict[str, Player]:
        return {pid: p for pid, p in self.players.items() if p.alive}

    def max_hand_for(self, p: Player) -> int:
        return min(3, p.balls_left)

    def max_guess(self) -> int:
        return sum(self.max_hand_for(p) for p in self.alive_players().values())

    def can_start(self) -> bool:
        alive = list(self.alive_players().values())
        if len(alive) < 2:
            return False
        return all(p.connected for p in alive)


# =========================
# APP
# =========================
app = FastAPI()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ROOMS: Dict[str, Room] = {}
ROOMS_LOCK = asyncio.Lock()


# =========================
# ORDEM / VEZ
# =========================
def alive_ids_in_base_order(room: Room) -> List[str]:
    ids: List[str] = []
    for pid in room.base_order:
        p = room.players.get(pid)
        if p and p.alive:
            ids.append(pid)
    return ids


def build_round_order(room: Room) -> None:
    alive_ids = alive_ids_in_base_order(room)
    if len(alive_ids) < 2:
        room.round_order = alive_ids
        return

    if room.starter_pid not in alive_ids:
        room.starter_pid = alive_ids[0]

    i = alive_ids.index(room.starter_pid)
    room.round_order = alive_ids[i:] + alive_ids[:i]


def next_turn_player(room: Room) -> Optional[str]:
    if room.phase not in ("hands", "guesses"):
        return None

    for pid in room.round_order:
        p = room.players.get(pid)
        if not p or not p.alive:
            continue
        if room.phase == "hands" and not p.hand_submitted:
            return pid
        if room.phase == "guesses" and not p.guess_submitted:
            return pid
    return None


def reset_round(room: Room) -> None:
    room.hands.clear()
    room.guesses.clear()
    room.used_guesses.clear()

    for p in room.players.values():
        p.hand_submitted = False
        p.guess_submitted = False

    build_round_order(room)
    room.turn_player_id = next_turn_player(room)


def rotate_starter(room: Room) -> None:
    alive_ids = alive_ids_in_base_order(room)
    if not alive_ids:
        room.starter_pid = None
        return
    if room.starter_pid not in alive_ids:
        room.starter_pid = alive_ids[0]
        return
    i = alive_ids.index(room.starter_pid)
    room.starter_pid = alive_ids[(i + 1) % len(alive_ids)]


def all_submitted(room: Room) -> bool:
    alive = room.alive_players()
    if room.phase == "hands":
        return all(p.hand_submitted for p in alive.values())
    if room.phase == "guesses":
        return all(p.guess_submitted for p in alive.values())
    return False


# =========================
# JOGO
# =========================
def start_game(room: Room) -> None:
    room.phase = "hands"
    room.round_num = 1
    alive_ids = alive_ids_in_base_order(room)
    room.starter_pid = alive_ids[0] if alive_ids else None
    reset_round(room)


def restart_game(room: Room) -> None:
    room.phase = "lobby"
    room.round_num = 0
    room.starter_pid = None
    room.round_order = []
    room.turn_player_id = None

    room.hands.clear()
    room.guesses.clear()
    room.used_guesses.clear()

    for p in room.players.values():
        p.balls_left = STARTING_BALLS
        p.hand_submitted = False
        p.guess_submitted = False


def pick_auto_guess(room: Room) -> int:
    mg = room.max_guess()
    for g in range(0, mg + 1):
        if g not in room.used_guesses:
            return g
    return 0


def resolve_reveal(room: Room) -> dict:
    total = sum(room.hands.values())

    winner_pid: Optional[str] = None
    for pid, g in room.guesses.items():
        if g == total:
            winner_pid = pid
            break

    winner_name = None
    if winner_pid is not None and winner_pid in room.players:
        w = room.players[winner_pid]
        w.balls_left -= 1
        winner_name = w.name

    details = []
    for pid in room.base_order:
        p = room.players.get(pid)
        if not p:
            continue
        details.append(
            {
                "player_id": pid,
                "name": p.name,
                "hand": room.hands.get(pid, 0),
                "guess": room.guesses.get(pid, None),
                "balls_after": p.balls_left,
                "alive_after": p.alive,
            }
        )

    game_over = None
    alive_after = room.alive_players()
    if len(alive_after) <= 1:
        room.phase = "over"
        room.turn_player_id = None

        loser = None
        if len(alive_after) == 1:
            loser = next(iter(alive_after.values())).name
        game_over = {"loser": loser, "reason": "last_player_standing"}

    result = {
        "round_num": room.round_num,
        "total": total,
        "hands": {room.players[pid].name: v for pid, v in room.hands.items() if pid in room.players},
        "guesses": {room.players[pid].name: v for pid, v in room.guesses.items() if pid in room.players},
        "winner": winner_name,
        "details": details,
    }
    return {"result": result, "game_over": game_over}


async def advance_phase_if_ready(room: Room) -> Optional[dict]:
    if room.phase == "hands" and all_submitted(room):
        room.phase = "guesses"
        room.turn_player_id = next_turn_player(room)
        return None

    if room.phase == "guesses" and all_submitted(room):
        room.phase = "reveal"
        reveal = resolve_reveal(room)

        if room.phase == "over":
            return {"type": "reveal", **reveal}

        rotate_starter(room)
        room.round_num += 1
        room.phase = "hands"
        reset_round(room)
        return {"type": "reveal", **reveal}

    return None


# =========================
# STATE / BROADCAST
# =========================
def room_public_state(room: Room) -> dict:
    players = []
    for p in room.players.values():
        players.append(
            {
                "player_id": p.player_id,
                "name": p.name,
                "balls_left": p.balls_left,
                "alive": p.alive,
                "connected": p.connected,
                "hand_submitted": p.hand_submitted if room.phase in ("hands", "guesses", "reveal", "over") else False,
                "guess_submitted": p.guess_submitted if room.phase in ("guesses", "reveal", "over") else False,
                "is_host": (p.player_id == room.host_player_id),
            }
        )
    players.sort(key=lambda x: (not x["alive"], x["name"].lower()))

    order_public = []
    for pid in room.round_order:
        p = room.players.get(pid)
        if p:
            order_public.append({"player_id": pid, "name": p.name})

    turn_name = None
    if room.turn_player_id and room.turn_player_id in room.players:
        turn_name = room.players[room.turn_player_id].name

    # palpites públicos em tempo real (nome + número)
    guesses_public: List[dict] = []
    if room.phase in ("guesses", "reveal", "over"):
        for pid in room.round_order:
            if pid in room.guesses and pid in room.players:
                guesses_public.append({"player_id": pid, "name": room.players[pid].name, "guess": room.guesses[pid]})

    return {
        "room_id": room.room_id,
        "phase": room.phase,
        "round_num": room.round_num,
        "host_player_id": room.host_player_id,
        "max_guess": room.max_guess() if room.phase in ("hands", "guesses") else None,
        "used_guesses": sorted(list(room.used_guesses)),
        "players": players,
        "round_order": order_public,
        "turn_player_id": room.turn_player_id,
        "turn_player_name": turn_name,
        "starter_player_id": room.starter_pid,
        "starter_player_name": room.players[room.starter_pid].name if room.starter_pid in room.players else None,
        "guesses_public": guesses_public,
    }


async def broadcast_room(room: Room, payload: dict) -> None:
    recipients: List[WebSocket] = []
    for p in room.players.values():
        if p.connected and p.ws is not None:
            recipients.append(p.ws)

    async def _send(ws: WebSocket) -> None:
        try:
            await safe_send(ws, payload)
        except Exception:
            pass

    await asyncio.gather(*(_send(ws) for ws in recipients))


async def push_state(room: Room) -> None:
    await broadcast_room(room, {"type": "state", "state": room_public_state(room)})


# =========================
# ROTAS HTTP
# =========================
@app.get("/")
async def root() -> HTMLResponse:
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/create-room")
async def api_create_room() -> dict:
    async with ROOMS_LOCK:
        rid = gen_room_id()
        while rid in ROOMS:
            rid = gen_room_id()
        ROOMS[rid] = Room(room_id=rid)
    return {"room_id": rid}


# =========================
# WEBSOCKET
# =========================
@app.websocket("/ws/{room_id}")
async def ws_room(
    websocket: WebSocket,
    room_id: str,
    name: str = Query(default="Jogador"),
    key: Optional[str] = Query(default=None),
) -> None:
    await websocket.accept()
    room_id = room_id.upper().strip()

    async with ROOMS_LOCK:
        room = ROOMS.get(room_id)
        if room is None:
            room = Room(room_id=room_id)
            ROOMS[room_id] = room

    player: Optional[Player] = None
    is_reconnect = False

    async with room.lock:
        room.touch()

        # reconectar por key
        if key:
            for p in room.players.values():
                if p.key == key:
                    player = p
                    is_reconnect = True
                    break

        # novo player
        if player is None:
            if len(room.players) >= MAX_PLAYERS_PER_ROOM:
                await safe_send(websocket, {"type": "error", "message": "Sala cheia (máx 10)."})
                await websocket.close()
                return

            pid = gen_player_id()
            pkey = gen_player_key()
            player = Player(
                player_id=pid,
                key=pkey,
                name=(name.strip() or "Jogador")[:20],
                ws=websocket,
                connected=True,
            )
            room.players[pid] = player
            room.base_order.append(pid)

            if room.host_player_id is None:
                room.host_player_id = pid

        # bind
        player.ws = websocket
        player.connected = True
        player.disconnected_at = None

        # se jogo já está rolando, e ordem/turn ficaram inconsistentes, tenta reconstruir
        if room.phase in ("hands", "guesses"):
            build_round_order(room)
            if room.turn_player_id is None:
                room.turn_player_id = next_turn_player(room)

    await safe_send(
        websocket,
        {
            "type": "joined",
            "room_id": room_id,
            "player_id": player.player_id,
            "player_key": player.key,
            "is_reconnect": is_reconnect,
        },
    )

    await push_state(room)

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")

            reveal_payload = None

            async with room.lock:
                room.touch()
                p = room.players.get(player.player_id)
                if p is None:
                    break

                if mtype == "start":
                    if p.player_id != room.host_player_id:
                        await safe_send(websocket, {"type": "error", "message": "Apenas o host pode iniciar."})
                        continue
                    if room.phase != "lobby":
                        await safe_send(websocket, {"type": "error", "message": "Jogo já está em andamento."})
                        continue
                    if not room.can_start():
                        await safe_send(websocket, {"type": "error", "message": "Precisa de pelo menos 2 jogadores vivos e conectados."})
                        continue
                    start_game(room)

                elif mtype == "restart":
                    if p.player_id != room.host_player_id:
                        await safe_send(websocket, {"type": "error", "message": "Apenas o host pode reiniciar."})
                        continue
                    restart_game(room)

                elif mtype == "skip":
                    # host pode destravar a vez atual
                    if p.player_id != room.host_player_id:
                        await safe_send(websocket, {"type": "error", "message": "Apenas o host pode pular vez."})
                        continue
                    if room.phase not in ("hands", "guesses"):
                        continue

                    cur = room.turn_player_id
                    if not cur or cur not in room.players:
                        continue
                    curp = room.players[cur]
                    if not curp.alive:
                        continue

                    if room.phase == "hands" and not curp.hand_submitted:
                        room.hands[cur] = 0
                        curp.hand_submitted = True

                    if room.phase == "guesses" and not curp.guess_submitted:
                        g = pick_auto_guess(room)
                        room.guesses[cur] = g
                        room.used_guesses.add(g)
                        curp.guess_submitted = True

                    room.turn_player_id = next_turn_player(room)
                    reveal_payload = await advance_phase_if_ready(room)

                elif mtype == "hand":
                    if room.phase != "hands":
                        continue
                    if not p.alive or p.hand_submitted:
                        continue
                    if room.turn_player_id != p.player_id:
                        await safe_send(websocket, {"type": "error", "message": "Não é sua vez."})
                        continue

                    v = int(msg.get("value", 0))
                    v = max(0, min(room.max_hand_for(p), v))

                    room.hands[p.player_id] = v
                    p.hand_submitted = True

                    room.turn_player_id = next_turn_player(room)
                    reveal_payload = await advance_phase_if_ready(room)

                elif mtype == "guess":
                    if room.phase != "guesses":
                        continue
                    if not p.alive or p.guess_submitted:
                        continue
                    if room.turn_player_id != p.player_id:
                        await safe_send(websocket, {"type": "error", "message": "Não é sua vez."})
                        continue

                    g = int(msg.get("value", 0))
                    g = max(0, min(room.max_guess(), g))

                    if g in room.used_guesses:
                        await safe_send(websocket, {"type": "error", "message": "Palpite já usado. Escolha outro."})
                        continue

                    room.guesses[p.player_id] = g
                    room.used_guesses.add(g)
                    p.guess_submitted = True

                    room.turn_player_id = next_turn_player(room)
                    reveal_payload = await advance_phase_if_ready(room)

                elif mtype == "leave":
                    room.players.pop(p.player_id, None)
                    if p.player_id in room.base_order:
                        room.base_order.remove(p.player_id)

                    if room.host_player_id == p.player_id:
                        room.host_player_id = next(iter(room.players.keys()), None)

                    if room.phase in ("hands", "guesses"):
                        reset_round(room)

                    break

            await push_state(room)
            if reveal_payload:
                await broadcast_room(room, reveal_payload)
                await push_state(room)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        async with room.lock:
            p = room.players.get(player.player_id)
            if p is not None:
                p.connected = False
                p.ws = None
                p.disconnected_at = now_ts()

        await push_state(room)


# =========================
# LIMPEZA
# =========================
async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(CLEANUP_EVERY_SECONDS)

        async with ROOMS_LOCK:
            to_delete: List[str] = []
            now = now_ts()

            for rid, room in ROOMS.items():
                async with room.lock:
                    purge_pids = []
                    for pid, p in room.players.items():
                        if not p.connected and p.disconnected_at is not None:
                            if (now - p.disconnected_at) > DISCONNECTED_PURGE_SECONDS:
                                purge_pids.append(pid)

                    for pid in purge_pids:
                        room.players.pop(pid, None)
                        if pid in room.base_order:
                            room.base_order.remove(pid)

                    if room.host_player_id not in room.players:
                        room.host_player_id = next(iter(room.players.keys()), None)

                    if not room.players and (now - room.updated_at) > ROOM_IDLE_PURGE_SECONDS:
                        to_delete.append(rid)

            for rid in to_delete:
                ROOMS.pop(rid, None)


@app.on_event("startup")
async def on_startup() -> None:
    asyncio.create_task(cleanup_loop())