<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>🎱 Jogo das Bolinhas (Online)</title>

  <style>
    :root{
      --bg: #0b0c10;
      --card: rgba(255,255,255,0.06);
      --border: rgba(255,255,255,0.10);
      --text: rgba(255,255,255,0.92);
      --muted: rgba(255,255,255,0.65);
      --good: #22c55e;
      --warn: #f59e0b;
      --bad: #ef4444;
      --shadow: 0 10px 30px rgba(0,0,0,0.35);
    }
    *{ box-sizing: border-box; }
    body{
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      color: var(--text);
      background:
        radial-gradient(1200px 600px at 20% 10%, rgba(34,197,94,0.18), transparent 60%),
        radial-gradient(1000px 600px at 85% 20%, rgba(59,130,246,0.18), transparent 55%),
        radial-gradient(900px 500px at 50% 90%, rgba(245,158,11,0.14), transparent 60%),
        var(--bg);
    }
    .wrap{ max-width: 1100px; margin: 24px auto; padding: 0 16px 40px; }
    h1{ margin: 8px 0 6px; font-size: 28px; }
    .subtitle{ margin: 0 0 14px; color: var(--muted); font-size: 14px; line-height: 1.35; }

    .card{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 14px;
      margin-top: 12px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }
    .row{ display:flex; gap: 12px; flex-wrap: wrap; align-items: end; }
    label{ font-size: 12px; color: var(--muted); display:inline-block; margin-bottom: 6px; }

    input, button{
      padding: 10px 12px;
      font-size: 16px;
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(0,0,0,0.25);
      color: var(--text);
      outline: none;
    }
    input{ min-width: 220px; }

    button{
      cursor: pointer;
      background: rgba(255,255,255,0.08);
      transition: transform .06s ease, background .12s ease, border-color .12s ease;
      user-select: none;
    }
    button:hover{ background: rgba(255,255,255,0.12); border-color: rgba(255,255,255,0.18); }
    button:active{ transform: translateY(1px); }
    button:disabled{ opacity: .5; cursor: not-allowed; transform:none; }

    .pills{ display:flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    .pill{
      display:inline-flex; gap: 8px; align-items:center;
      padding: 7px 10px; border-radius: 999px;
      background: rgba(255,255,255,0.07);
      border: 1px solid rgba(255,255,255,0.10);
      font-size: 13px; color: var(--muted);
    }
    .dot{ width: 10px; height: 10px; border-radius: 999px; background: rgba(255,255,255,0.28); }
    .dot.on{ background: var(--good); }
    .dot.off{ background: rgba(148,163,184,0.75); }

    .error{ color: #fecaca; margin: 10px 0 0; }
    .hint{ color: var(--muted); margin: 8px 0 0; font-size: 13px; }
    .sep{ height:1px; background: rgba(255,255,255,0.10); margin: 12px 0; }

    .orderBar{
      display:flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; align-items:center;
    }
    .chip{
      padding: 7px 10px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(255,255,255,0.07);
      font-size: 13px;
      color: rgba(255,255,255,0.86);
      display:inline-flex;
      gap: 8px;
      align-items:center;
      white-space: nowrap;
    }
    .chip .miniDot{ width: 8px; height: 8px; border-radius: 999px; background: rgba(255,255,255,0.25); }
    .chip.turn{
      background: rgba(245,158,11,0.18);
      border-color: rgba(245,158,11,0.30);
      box-shadow: 0 0 0 3px rgba(245,158,11,0.10);
    }
    .chip.turn .miniDot{ background: var(--warn); }

    .playersGrid{ display:grid; gap: 10px; }
    .playerRow{
      display:grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items:center;
      padding: 12px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(255,255,255,0.05);
      border-radius: 14px;
      transition: transform .10s ease, border-color .10s ease, background .10s ease;
    }
    .playerRow.turnPlayer{
      border-color: rgba(245,158,11,0.35);
      background: rgba(245,158,11,0.10);
      box-shadow: 0 0 0 3px rgba(245,158,11,0.10);
      transform: translateY(-1px);
    }
    .turnName{
      color: rgba(255,255,255,0.98);
      text-shadow: 0 0 18px rgba(245,158,11,0.35);
    }

    .nameLine{ display:flex; gap: 8px; flex-wrap: wrap; align-items:center; }
    .miniTag{
      font-size: 12px; padding: 3px 8px; border-radius: 999px;
      background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.10);
      color: rgba(255,255,255,0.80);
    }
    .miniTag.host{ background: rgba(245,158,11,0.14); border-color: rgba(245,158,11,0.18); }
    .miniTag.ok{ background: rgba(34,197,94,0.14); border-color: rgba(34,197,94,0.18); }
    .miniTag.wait{ background: rgba(148,163,184,0.12); border-color: rgba(148,163,184,0.16); }

    .rightBox{ display:grid; gap: 8px; justify-items:end; }
    .balls{ display:inline-flex; gap: 5px; align-items:center; }
    .ball{
      width: 11px; height: 11px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.50);
      background: transparent;
    }
    .ball.filled{ background: rgba(255,255,255,0.92); border-color: rgba(255,255,255,0.72); }
    .barWrap{
      height: 10px; width: 170px;
      background: rgba(255,255,255,0.10);
      border: 1px solid rgba(255,255,255,0.10);
      border-radius: 999px;
      overflow: hidden;
    }
    .barFill{ height: 100%; width: 0%; background: rgba(255,255,255,0.85); transition: width .35s ease; }

    .actionsBox p{ margin: 8px 0; color: var(--muted); }
    .quick{ display:flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
    .quick button{ font-size: 13px; padding: 8px 10px; border-radius: 999px; }

    /* botão kick */
    .kickBtn{
      font-size: 12px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(239,68,68,0.25);
      background: rgba(239,68,68,0.12);
      color: rgba(255,255,255,0.92);
    }
    .kickBtn:hover{ border-color: rgba(239,68,68,0.35); background: rgba(239,68,68,0.18); }

    /* Overlay resultado (mantém) */
    .overlay{
      position: fixed; inset: 0;
      background: rgba(0,0,0,0.55);
      display: none; align-items: center; justify-content: center;
      padding: 18px; z-index: 50;
    }
    .overlay.show{ display:flex; }
    .modal{
      width: min(900px, 100%);
      background: rgba(20, 20, 24, 0.88);
      border: 1px solid rgba(255,255,255,0.14);
      border-radius: 18px;
      padding: 16px;
      box-shadow: 0 30px 80px rgba(0,0,0,0.55);
      backdrop-filter: blur(12px);
      position: relative;
    }
    .closeBtn{ position:absolute; top: 12px; right: 12px; padding: 8px 10px; border-radius: 12px; }
    .modal h3{ margin: 0 0 8px; }
    .modal .meta{ color: var(--muted); font-size: 13px; margin: 0 0 12px; }
    .bigTotal{ display:flex; gap: 12px; flex-wrap: wrap; align-items:center; margin: 10px 0 12px; }
    .bigTotal .num{ font-size: 40px; font-weight: 850; }
    .winnerLine{
      margin-left: auto;
      padding: 8px 10px; border-radius: 14px;
      border: 1px solid rgba(34,197,94,0.22);
      background: rgba(34,197,94,0.12);
      font-size: 13px;
      display:flex; gap: 10px; align-items:center;
    }
    .ovTimerWrap{ margin-top: 10px; display: grid; gap: 6px; }
    .ovTimerBar{
      height: 10px; border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(255,255,255,0.08);
      overflow: hidden;
      box-shadow: inset 0 6px 16px rgba(0,0,0,0.20);
    }
    .ovTimerFill{
      height: 100%;
      width: 100%;
      background: rgba(255,255,255,0.85);
      transition: width .05s linear;
    }
    .ovTimerText{ color: var(--muted); font-size: 13px; }

    @media (max-width: 680px){
      input{ min-width: 160px; width: 100%; }
      .barWrap{ width: 140px; }
    }
  </style>
</head>

<body>
  <div class="wrap">
    <h1>🎱 Jogo das Bolinhas (Online)</h1>
    <p class="subtitle">
      Agora com reconexão automática + keepalive + host pode expulsar 👀
    </p>

    <div class="card">
      <div class="row">
        <div>
          <label>Seu nome</label><br/>
          <input id="name" placeholder="Leandro" />
        </div>
        <div>
          <label>Sala</label><br/>
          <input id="room" placeholder="ABC123" />
        </div>
        <button id="create">Criar sala</button>
        <button id="connect">Conectar</button>
        <button id="copyLink">Copiar link</button>
      </div>

      <div class="sep"></div>

      <div class="row">
        <button id="start" disabled>Iniciar (host)</button>
        <button id="restart" disabled>Reiniciar (host)</button>
        <button id="skip" disabled>Pular vez (host)</button>

        <div class="pills">
          <span class="pill"><span class="dot off" id="connDot"></span> <span id="connStatus">Desconectado</span></span>
          <span class="pill" id="phasePill">fase: -</span>
          <span class="pill" id="roundPill">rodada: -</span>
          <span class="pill" id="roomPill">sala: -</span>
          <span class="pill" id="turnPill">vez: -</span>
        </div>
      </div>

      <div class="orderBar" id="orderBar"></div>

      <p id="err" class="error"></p>
      <p id="hint" class="hint"></p>
    </div>

    <div class="card actionsBox">
      <h3 style="margin:0 0 8px;">Ações</h3>

      <div id="handBox" style="display:none;">
        <p><b>Mão fechada:</b> escolha 0–3 (limitado ao seu estoque). Só aparece quando for sua vez.</p>
        <div class="row">
          <input id="hand" type="number" min="0" max="3" value="0" />
          <button id="sendHand">Enviar mão</button>
          <span id="handAck" style="color: var(--good); font-weight: 650;"></span>
        </div>
        <div class="quick" id="handQuick"></div>
      </div>

      <div id="guessBox" style="display:none;">
        <p><b>Palpite:</b> sem repetir. Máximo desta rodada: <b><span id="maxGuess">-</span></b></p>
        <div class="row">
          <input id="guess" type="number" min="0" value="0" />
          <button id="sendGuess">Enviar palpite</button>
          <span id="guessAck" style="color: var(--good); font-weight: 650;"></span>
        </div>
        <p class="subtitle" style="margin-top:10px;">
          Palpites já dados: <span id="usedGuesses">-</span>
        </p>
      </div>

      <div id="waitingBox" style="display:none;">
        <p class="subtitle" id="waitingText">Aguardando...</p>
      </div>
    </div>

    <div class="card">
      <h3 style="margin:0 0 8px;">Jogadores</h3>
      <div id="players" class="playersGrid"></div>
    </div>
  </div>

  <!-- Reveal Overlay -->
  <div class="overlay" id="overlay">
    <div class="modal" role="dialog" aria-modal="true" aria-label="Resultado da rodada">
      <button class="closeBtn" id="closeOverlay">Fechar</button>
      <h3 id="ovTitle">Revelação</h3>
      <p class="meta" id="ovMeta">-</p>

      <div class="bigTotal">
        <div>
          <div class="num" id="ovTotal">0</div>
          <div class="subtitle" style="margin:0;">Total de bolinhas na rodada</div>
        </div>
        <div class="winnerLine" id="ovWinner" style="display:none;">
          <span>🏆</span>
          <span id="ovWinnerText">-</span>
        </div>
      </div>

      <div class="ovTimerWrap">
        <div class="ovTimerBar"><div class="ovTimerFill" id="ovTimerFill"></div></div>
        <div class="ovTimerText" id="ovTimerText">Fechando em...</div>
      </div>
    </div>
  </div>

<script>
  const $ = (id) => document.getElementById(id);

  let ws = null;
  let playerId = null;
  let state = null;

  // keepalive
  let pingTimer = null;

  // reconexão
  let reconnectTimer = null;
  let reconnectAttempts = 0;
  let manualClose = false;

  // overlay timer
  const OVERLAY_MS = 6500;
  const OVERLAY_GAMEOVER_MS = 10000;
  let overlayTimeout = null;
  let overlayInterval = null;

  function setError(msg = "") { $("err").textContent = msg; }
  function setHint(msg = "") { $("hint").textContent = msg; }

  function roomKeyStorageKey(roomId) { return `bolinhas:key:${roomId}`; }
  function currentRoom() { return ($("room").value || "").trim().toUpperCase(); }
  function setConnected(ok) {
    $("connStatus").textContent = ok ? "Conectado" : "Desconectado";
    $("connDot").className = `dot ${ok ? "on" : "off"}`;
  }

  function showBoxes({ hand=false, guess=false, waiting=false } = {}) {
    $("handBox").style.display = hand ? "block" : "none";
    $("guessBox").style.display = guess ? "block" : "none";
    $("waitingBox").style.display = waiting ? "block" : "none";
  }

  function you() {
    if (!state || !playerId) return null;
    return state.players.find(p => p.player_id === playerId) || null;
  }
  function isHost() { return state && playerId && state.host_player_id === playerId; }
  function clamp(n, a, b) { return Math.max(a, Math.min(b, n)); }

  // ===== overlay timer =====
  function stopOverlayTimers(){
    if (overlayTimeout) clearTimeout(overlayTimeout);
    if (overlayInterval) clearInterval(overlayInterval);
    overlayTimeout = null;
    overlayInterval = null;
  }
  function startOverlayTimer(durationMs){
    stopOverlayTimers();

    const start = Date.now();
    const end = start + durationMs;

    function tick(){
      const now = Date.now();
      const remain = Math.max(0, end - now);
      const frac = remain / durationMs;

      $("ovTimerFill").style.width = `${(frac * 100).toFixed(1)}%`;
      $("ovTimerText").textContent = `Fechando em ${Math.ceil(remain/1000)}s`;

      if (remain <= 0) {
        $("overlay").classList.remove("show");
        stopOverlayTimers();
      }
    }

    tick();
    overlayInterval = setInterval(tick, 50);
    overlayTimeout = setTimeout(() => {
      $("overlay").classList.remove("show");
      stopOverlayTimers();
    }, durationMs);
  }

  function showOverlay(result, gameOver) {
    $("overlay").classList.add("show");
    $("ovTitle").textContent = `Revelação — Rodada ${result.round_num}`;
    $("ovMeta").textContent = gameOver
      ? `Fim de jogo! Perdedor: ${gameOver.loser ?? "Empate raro"}`
      : "Resultado da rodada.";
    $("ovTotal").textContent = String(result.total);

    if (result.winner) {
      $("ovWinner").style.display = "flex";
      $("ovWinnerText").textContent = `${result.winner} acertou e perde 1 bolinha`;
    } else {
      $("ovWinner").style.display = "none";
      $("ovWinnerText").textContent = "";
    }
    startOverlayTimer(gameOver ? OVERLAY_GAMEOVER_MS : OVERLAY_MS);
  }

  $("closeOverlay").onclick = () => { $("overlay").classList.remove("show"); stopOverlayTimers(); };
  $("overlay").onclick = (e) => { if (e.target === $("overlay")) { $("overlay").classList.remove("show"); stopOverlayTimers(); } };

  // ===== UI =====
  function renderOrderBar(s) {
    const bar = $("orderBar");
    bar.innerHTML = "";

    if (!s.round_order || !s.round_order.length || s.phase === "lobby") {
      const c = document.createElement("div");
      c.className = "chip";
      c.innerHTML = `<span class="miniDot"></span><span>Ordem: (ainda não começou)</span>`;
      bar.appendChild(c);
      return;
    }

    s.round_order.forEach((pl, idx) => {
      const chip = document.createElement("div");
      chip.className = "chip" + (pl.player_id === s.turn_player_id ? " turn" : "");
      chip.innerHTML = `<span class="miniDot"></span><span>${idx+1}. ${pl.name}</span>`;
      bar.appendChild(chip);
    });
  }

  function ballsHTML(ballsLeft, maxBalls = 3) {
    const wrap = document.createElement("span");
    wrap.className = "balls";
    for (let i = 0; i < maxBalls; i++) {
      const b = document.createElement("span");
      b.className = "ball" + (i < ballsLeft ? " filled" : "");
      wrap.appendChild(b);
    }
    return wrap;
  }

  function renderPlayers(s) {
    const list = $("players");
    list.innerHTML = "";

    s.players.forEach(p => {
      const row = document.createElement("div");
      row.className = "playerRow";

      const isTurn = (p.player_id === s.turn_player_id);
      if (isTurn) row.classList.add("turnPlayer");

      const pct = clamp((p.balls_left / 3) * 100, 0, 100);

      row.innerHTML = `
        <div>
          <div class="nameLine">
            <b class="${isTurn ? "turnName" : ""}"></b>
            ${p.is_host ? `<span class="miniTag host">host</span>` : ""}
            ${!p.alive ? `<span class="miniTag">fora</span>` : ""}
            ${(s.phase !== "lobby")
              ? `<span class="miniTag ${p.hand_submitted ? "ok" : "wait"}">mão ${p.hand_submitted ? "✅" : "⏳"}</span>` : ""}
            ${(s.phase === "guesses" || s.phase === "reveal" || s.phase === "over")
              ? `<span class="miniTag ${p.guess_submitted ? "ok" : "wait"}">palpite ${p.guess_submitted ? "✅" : "⏳"}</span>` : ""}
            ${isTurn ? `<span class="miniTag host">VEZ</span>` : ""}
          </div>
          <div class="subtitle" style="margin:6px 0 0;">
            ${p.connected ? "🟢 online" : "⚫ offline"} • estoque: ${p.balls_left}/3
          </div>
        </div>
        <div class="rightBox"></div>
      `;

      row.querySelector("b").textContent = p.name + (p.player_id === playerId ? " (VOCÊ)" : "");

      const rb = row.querySelector(".rightBox");
      rb.appendChild(ballsHTML(p.balls_left, 3));

      const barWrap = document.createElement("div");
      barWrap.className = "barWrap";
      const barFill = document.createElement("div");
      barFill.className = "barFill";
      barFill.style.width = `${pct}%`;
      barWrap.appendChild(barFill);
      rb.appendChild(barWrap);

      // botão expulsar (host)
      if (isHost() && p.player_id !== playerId) {
        const kick = document.createElement("button");
        kick.className = "kickBtn";
        kick.textContent = "Expulsar";
        kick.onclick = () => {
          const ok = confirm(`Remover "${p.name}" da sala?`);
          if (ok) send("kick", { target_id: p.player_id });
        };
        rb.appendChild(kick);
      }

      list.appendChild(row);
    });
  }

  function renderHandQuick(maxHand) {
    const q = $("handQuick");
    q.innerHTML = "";
    for (let v = 0; v <= 3; v++) {
      const b = document.createElement("button");
      b.textContent = `${v}`;
      b.disabled = v > maxHand;
      b.onclick = () => { $("hand").value = String(v); };
      q.appendChild(b);
    }
  }

  function renderGuessesPublic(s) {
    $("usedGuesses").textContent = (s.used_guesses || []).join(", ") || "-";
    const gp = s.guesses_public || [];
    if (s.phase === "guesses" && gp.length) {
      $("usedGuesses").textContent = gp.map(x => `${x.name}: ${x.guess}`).join("  •  ");
    }
  }

  function renderState(s) {
    state = s;

    $("phasePill").textContent = `fase: ${s.phase}`;
    $("roundPill").textContent = `rodada: ${s.round_num || "-"}`;
    $("roomPill").textContent = `sala: ${s.room_id || "-"}`;
    $("turnPill").textContent = s.turn_player_name ? `vez: ${s.turn_player_name}` : "vez: -";

    $("start").disabled = !(s.phase === "lobby" && isHost());
    $("restart").disabled = !isHost();
    $("skip").disabled = !(isHost() && (s.phase === "hands" || s.phase === "guesses"));

    $("maxGuess").textContent = (s.max_guess ?? "-");

    renderGuessesPublic(s);
    renderOrderBar(s);
    renderPlayers(s);

    const me = you();
    $("handAck").textContent = "";
    $("guessAck").textContent = "";

    if (!me) {
      showBoxes({ waiting: true });
      $("waitingText").textContent = "Você ainda não foi reconhecido na sala.";
      return;
    }

    if (!me.alive && s.phase !== "lobby") {
      showBoxes({ waiting: true });
      $("waitingText").textContent = "Você está fora do jogo. Agora é espectador. 🍿";
      return;
    }

    if (s.phase === "lobby") {
      showBoxes({ waiting: true });
      $("waitingText").textContent = isHost()
        ? "Você é o host. Quando tiver pelo menos 2 jogadores, clique em Iniciar."
        : "Aguardando o host iniciar...";
      return;
    }

    if (s.phase === "hands") {
      if (me.hand_submitted) {
        showBoxes({ waiting: true });
        $("waitingText").textContent = `Você já enviou sua mão. Aguardando... (Vez de: ${s.turn_player_name || "?"})`;
        return;
      }
      if (s.turn_player_id !== me.player_id) {
        showBoxes({ waiting: true });
        $("waitingText").textContent = `Aguardando... agora é a vez de ${s.turn_player_name || "alguém"}.`;
        return;
      }

      const maxHand = Math.min(3, me.balls_left);
      $("hand").max = String(maxHand);
      $("hand").value = "0";
      renderHandQuick(maxHand);
      showBoxes({ hand: true });
      return;
    }

    if (s.phase === "guesses") {
      if (me.guess_submitted) {
        showBoxes({ waiting: true });
        $("waitingText").textContent = `Você já enviou seu palpite. Aguardando... (Vez de: ${s.turn_player_name || "?"})`;
        return;
      }
      if (s.turn_player_id !== me.player_id) {
        showBoxes({ waiting: true });
        $("waitingText").textContent = `Aguardando... agora é a vez de ${s.turn_player_name || "alguém"}.`;
        return;
      }

      $("guess").min = "0";
      $("guess").max = String(s.max_guess ?? 0);
      $("guess").value = "0";
      showBoxes({ guess: true });
      return;
    }

    showBoxes({ waiting: true });
    $("waitingText").textContent = s.phase === "over"
      ? (isHost() ? "Fim de jogo. Você pode reiniciar se quiser." : "Fim de jogo. Aguarde o host reiniciar.")
      : "Revelando resultado...";
  }

  // ===== conexão + reconexão =====
  function stopPing(){
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = null;
  }

  function startPing(){
    stopPing();
    pingTimer = setInterval(() => {
      if (ws && ws.readyState === 1) {
        try { ws.send(JSON.stringify({ type: "ping" })); } catch {}
      }
    }, 20000); // 20s
  }

  function scheduleReconnect(immediate=false){
    if (manualClose) return;

    clearTimeout(reconnectTimer);
    const base = immediate ? 200 : 600;
    const delay = Math.min(15000, base * Math.pow(2, reconnectAttempts)) + Math.floor(Math.random() * 400);
    reconnectAttempts++;

    setHint(`Reconectando em ${Math.ceil(delay/1000)}s...`);
    reconnectTimer = setTimeout(() => {
      if (!manualClose) connect(true);
    }, delay);
  }

  function connect(isAuto=false) {
    setError("");

    const name = ($("name").value || "Jogador").trim();
    const room = currentRoom();
    if (!room) { setError("Informe uma sala ou clique em Criar sala."); return; }

    const storedKey = localStorage.getItem(roomKeyStorageKey(room));
    const keyParam = storedKey ? `&key=${encodeURIComponent(storedKey)}` : "";

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws/${room}?name=${encodeURIComponent(name)}${keyParam}`;

    try {
      if (ws && ws.readyState === 1) ws.close();
    } catch {}

    ws = new WebSocket(url);

    ws.onopen = () => {
      setConnected(true);
      reconnectAttempts = 0;
      if (isAuto) setHint("Reconectado ✅");
      else setHint(`Conectado na sala ${room}.`);
      startPing();
    };

    ws.onclose = () => {
      setConnected(false);
      stopPing();
      if (!manualClose) scheduleReconnect(false);
    };

    ws.onerror = () => {
      setError("Erro no WebSocket.");
    };

    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);

      if (msg.type === "error") { setError(msg.message); return; }
      if (msg.type === "pong") { return; }

      if (msg.type === "kicked") {
        manualClose = true;
        stopPing();
        setError(msg.message || "Você foi removido.");
        try { ws.close(); } catch {}
        return;
      }

      if (msg.type === "joined") {
        playerId = msg.player_id;
        $("room").value = msg.room_id;
        localStorage.setItem(roomKeyStorageKey(msg.room_id), msg.player_key);
        location.hash = msg.room_id;
        if (!isAuto) setHint(`Entrou na sala ${msg.room_id}.`);
        return;
      }

      if (msg.type === "state") { renderState(msg.state); return; }
      if (msg.type === "reveal") { showOverlay(msg.result, msg.game_over); return; }
    };
  }

  function send(type, payload = {}) {
    setError("");
    if (!ws || ws.readyState !== 1) { setError("Você não está conectado (tentando reconectar...)."); scheduleReconnect(true); return; }
    ws.send(JSON.stringify({ type, ...payload }));
  }

  $("create").onclick = async () => {
    setError("");
    const res = await fetch("/api/create-room");
    const data = await res.json();
    $("room").value = data.room_id;
    location.hash = data.room_id;
    setHint(`Sala criada: ${data.room_id}. Clique em Conectar.`);
  };

  $("connect").onclick = () => {
    manualClose = false;
    connect(false);
  };

  $("copyLink").onclick = async () => {
    const room = currentRoom();
    if (!room) return setError("Sem sala para copiar link.");
    const url = `${location.origin}/#${room}`;
    try { await navigator.clipboard.writeText(url); setHint("Link copiado!"); }
    catch { setHint(url); }
  };

  $("start").onclick = () => send("start");
  $("restart").onclick = () => send("restart");
  $("skip").onclick = () => send("skip");

  $("sendHand").onclick = () => {
    const v = parseInt($("hand").value || "0", 10);
    send("hand", { value: v });
    $("handAck").textContent = "Mão enviada ✅";
  };

  $("sendGuess").onclick = () => {
    const v = parseInt($("guess").value || "0", 10);
    if (state && state.used_guesses && state.used_guesses.includes(v)) {
      setError("Esse palpite já foi usado. Escolha outro.");
      return;
    }
    send("guess", { value: v });
    $("guessAck").textContent = "Palpite enviado ✅";
  };

  // quando voltar pra aba, tenta reconectar rápido se caiu
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      if (!ws || ws.readyState !== 1) scheduleReconnect(true);
    }
  });

  // se fechar a aba, encerra sem ficar tentando reconectar
  window.addEventListener("beforeunload", () => {
    manualClose = true;
    stopPing();
    try { if (ws) ws.close(); } catch {}
  });

  window.addEventListener("load", () => {
    const hash = (location.hash || "").replace("#", "").trim().toUpperCase();
    if (hash) $("room").value = hash;
  });
</script>
</body>
</html>