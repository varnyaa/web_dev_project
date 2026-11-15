const $ = id => document.getElementById(id);
const EMOJI = {joy:"😊", sadness:"😢", anger:"😠", anxiety:"😰", stress:"😣", loneliness:"🫂", neutral:"😐", crisis:"🆘"};
const STAGES = ["Safety check", "Emotion detection", "Response", "Coping tool", "Mood log"];
const SAMPLES = ["Hello", "I'm so stressed about my exams", "I can't sleep at night", "I feel really lonely here",
                 "I got an A today, I'm so happy!", "I'm worried I'll fail and can't stop overthinking", "I don't want to live anymore"];

const uid = localStorage.getItem("mw_uid") || (() => {
  const id = "u" + Math.random().toString(36).slice(2) + Date.now().toString(36);
  localStorage.setItem("mw_uid", id); return id;
})();
let history = [];
let busy = false;
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function api(path, method = "GET", body) {
  const res = await fetch(path, {method, headers: {"Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
  if (!res.ok) throw new Error("Request failed");
  return res.json();
}

/* ---------- pipeline bar ---------- */
function buildPipeline() {
  $("pipeline").innerHTML = "";
  STAGES.forEach((s, i) => {
    const d = document.createElement("div");
    d.className = "step"; d.id = "st" + i;
    d.innerHTML = `<b>${i + 1}. ${s}</b><small>waiting…</small>`;
    $("pipeline").appendChild(d);
  });
}
async function animatePipeline(stages, crisis) {
  for (let i = 0; i < stages.length; i++) {
    const el = $("st" + i);
    el.className = "step active"; await sleep(260);
    el.className = "step " + (crisis && i === 0 ? "alert" : "done");
    el.querySelector("small").textContent = stages[i].result;
  }
}

/* ---------- messages ---------- */
function scroll() { $("messages").scrollTop = $("messages").scrollHeight; }
function addUser(text) {
  const d = document.createElement("div"); d.className = "msg user"; d.textContent = text;
  $("messages").appendChild(d); scroll();
}
function addBot(data) {
  const d = document.createElement("div");
  d.className = data.crisis ? "crisis" : "msg bot";
  const p = document.createElement("div"); p.textContent = data.reply; d.appendChild(p);
  if (data.crisis) {
    data.helplines.forEach(h => {
      const a = document.createElement("a");
      if (h.number) { a.href = "tel:" + h.number; a.textContent = `📞 ${h.name}: ${h.number}`; }
      else { a.href = "https://findahelpline.com"; a.target = "_blank"; a.rel = "noopener"; a.className = "plain"; a.textContent = "🌍 " + h.name; }
      d.appendChild(a);
    });
  } else {
    const m = document.createElement("div"); m.className = "meta";
    const chip = document.createElement("span"); chip.className = "chip";
    chip.textContent = `${EMOJI[data.emotion]} ${data.emotion}`; m.appendChild(chip);
    const q = document.createElement("span"); q.textContent = "Helpful?"; m.appendChild(q);
    [["👍", 1], ["👎", -1]].forEach(([e, r]) => {
      const b = document.createElement("button"); b.className = "fb"; b.textContent = e;
      b.onclick = async () => {
        await api("/api/feedback", "POST", {uid, key: data.key, rating: r}).catch(() => {});
        m.textContent = "Thanks for your feedback 💙";
      };
      m.appendChild(b);
    });
    d.appendChild(m);
  }
  $("messages").appendChild(d); scroll();
}
function typing(on) {
  if (on) {
    const t = document.createElement("div"); t.id = "typing"; t.className = "msg bot typing";
    t.innerHTML = "<i></i><i></i><i></i>"; $("messages").appendChild(t); scroll();
  } else if ($("typing")) $("typing").remove();
}

/* ---------- coping tool ---------- */
function showExercise(ex) {
  const box = $("exercise");
  box.innerHTML = "<h3>🧘 Coping tool</h3>";
  if (!ex) { box.innerHTML += '<div class="muted">Please reach out to the helplines shown in the chat.</div>'; return; }
  const n = document.createElement("div"); n.className = "ex-name"; n.textContent = ex.name; box.appendChild(n);
  if (ex.type === "breathing") { const b = document.createElement("div"); b.className = "breath"; b.textContent = "breathe"; box.appendChild(b); }
  const ol = document.createElement("ol");
  ex.steps.forEach(s => { const li = document.createElement("li"); li.textContent = s; ol.appendChild(li); });
  box.appendChild(ol);
}

/* ---------- mood chart ---------- */
async function loadMoods() {
  let moods = [];
  try { moods = (await api("/api/moods?uid=" + uid)).moods; } catch (e) {}
  drawChart(moods);
  if (!moods.length) { $("stats").textContent = "No entries yet"; return; }
  const avg = (moods.reduce((a, m) => a + m.score, 0) / moods.length).toFixed(1);
  $("stats").textContent = `${moods.length} check-ins · average mood ${avg}/5`;
}
function drawChart(moods) {
  const cv = $("chart"), dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 300, H = 190;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  const pad = {l: 26, r: 14, t: 16, b: 14};
  const y = v => pad.t + (5 - v) / 4 * (H - pad.t - pad.b);
  g.font = "11px Segoe UI, sans-serif"; g.fillStyle = "#a9aed0"; g.strokeStyle = "rgba(255,255,255,.1)";
  for (let v = 1; v <= 5; v++) { g.beginPath(); g.moveTo(pad.l, y(v)); g.lineTo(W - pad.r, y(v)); g.stroke(); g.fillText(v, 8, y(v) + 4); }
  if (!moods.length) { g.fillText("Your mood chart will appear here", pad.l + 40, H / 2); return; }
  const x = i => moods.length === 1 ? (W + pad.l) / 2 : pad.l + 10 + i * (W - pad.l - pad.r - 20) / (moods.length - 1);
  const grad = g.createLinearGradient(0, 0, W, 0); grad.addColorStop(0, "#7c6cff"); grad.addColorStop(1, "#27d3c3");
  g.strokeStyle = grad; g.lineWidth = 3; g.lineJoin = "round"; g.beginPath();
  moods.forEach((m, i) => i ? g.lineTo(x(i), y(m.score)) : g.moveTo(x(i), y(m.score))); g.stroke();
  g.font = "16px sans-serif"; g.textAlign = "center";
  moods.forEach((m, i) => g.fillText(EMOJI[m.emotion] || "😐", x(i), y(m.score) + 5));
  g.textAlign = "start";
}

/* ---------- send flow ---------- */
async function send(text) {
  text = (text || $("input").value).trim();
  if (!text || busy) return;
  busy = true; $("send").disabled = true; $("input").value = "";
  addUser(text); typing(true); buildPipeline();
  try {
    const data = await api("/api/chat", "POST", {uid, message: text, history});
    await animatePipeline(data.stages, data.crisis);
    typing(false); addBot(data); showExercise(data.exercise); loadStatus();
    history.push({role: "user", content: text}, {role: "assistant", content: data.reply});
    history = history.slice(-12);
    loadMoods();
  } catch (e) {
    typing(false);
    addBot({reply: "Sorry, I couldn't reach the server. Please make sure app.py is running.", emotion: "neutral", key: "err"});
  }
  busy = false; $("send").disabled = false; $("input").focus();
}

/* ---------- AI status badge ---------- */
async function loadStatus() {
  const b = $("status");
  try {
    const s = await api("/api/status");
    if (!s.llm) { b.className = "badge"; b.textContent = "⚪ Offline mode (built-in CBT)"; b.title = "Add GEMINI_API_KEY to the .env file to enable Gemini"; }
    else if (s.error) { b.className = "badge warn"; b.textContent = "🟡 Gemini issue – using built-in"; b.title = s.error; }
    else { b.className = "badge on"; b.textContent = "🟢 Gemini AI" + (s.model ? " · " + s.model : ""); b.title = "Free Gemini API connected"; }
  } catch (e) { b.textContent = "server offline"; }
}

/* ---------- init ---------- */
$("send").onclick = () => send();
$("input").addEventListener("keydown", e => { if (e.key === "Enter") send(); });
$("agree").onclick = () => { localStorage.setItem("mw_consent", "1"); $("consent").classList.add("hide"); $("input").focus(); };
$("wipe").onclick = async () => {
  if (!confirm("Delete all your saved mood data? This cannot be undone.")) return;
  await api("/api/data?uid=" + uid, "DELETE").catch(() => {});
  history = []; $("messages").innerHTML = ""; welcome(); loadMoods(); buildPipeline();
};
function welcome() {
  addBot({reply: "Hi, I'm MindEase 💙 This is a safe, private space to talk about stress, anxiety, low mood, loneliness, sleep or anything on your mind. How are you feeling today?", emotion: "neutral", key: "welcome"});
}
if (localStorage.getItem("mw_consent")) $("consent").classList.add("hide");
SAMPLES.forEach(s => {
  const b = document.createElement("button"); b.textContent = s; b.onclick = () => send(s); $("samples").appendChild(b);
});
window.addEventListener("resize", loadMoods);
buildPipeline(); welcome(); loadMoods(); loadStatus();
