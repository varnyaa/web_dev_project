"""MindEase - Mental Wellness AI Chatbot backend (Python standard library only, no installs needed).
Pipeline: user input -> safety check -> emotion detection -> response -> coping tool + mood log -> feedback
Run:  python app.py   then open http://localhost:8000
AI replies use the FREE Google Gemini API: paste your key into api_key.txt (or .env -> GEMINI_API_KEY=your_key)
Without a key (or if Gemini is busy) the built-in CBT dialogue engine answers, so the bot always works."""
import json, os, random, re, sqlite3, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "wellness.db")

def load_env():  # reads KEY=VALUE lines from .env so no terminal setup is needed
    p = os.path.join(BASE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8-sig"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
load_env()

PORT = int(os.environ.get("PORT", 8000))
API_KEY = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
if not API_KEY:  # easiest option: paste the key into api_key.txt (a normal, visible file)
    try:
        _w = open(os.path.join(BASE, "api_key.txt"), encoding="utf-8-sig").read().split()
        API_KEY = _w[0] if _w else ""
    except OSError:
        pass
if API_KEY.lower().startswith("your") or "paste" in API_KEY.lower():
    API_KEY = ""  # placeholder text, not a real key
GEM = os.environ.get("GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta")
PREFERRED = os.environ.get("GEMINI_MODEL", "").strip()
# free-tier Flash models, tried in order; unavailable ones are skipped automatically
DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite"]
BAD, STATE = set(), {"model": None, "error": ""}

# ---------- 1. SAFETY LAYER ----------
# CRISIS: Stores high-risk phrases and keywords indicating immediate self-harm or severe mental health emergencies.
# When matched, the app bypasses standard responses to trigger urgent crisis intervention resources.
CRISIS = [r"kill myself", r"suicid", r"end my life", r"want to die", r"wanna die", r"don'?t want to (live|be here|exist)",
          r"better off dead", r"end it all", r"hurt myself", r"self[- ]?harm", r"cut myself", r"no reason to live",
          r"can'?t go on", r"take my own life", r"not worth living"]
HELPLINES = [
    {"name": "Tele-MANAS (India, 24/7, free)", "number": "14416"},
    {"name": "KIRAN Mental Health Helpline (India)", "number": "18005990019"},
    {"name": "Emergency services (India)", "number": "112"},
    {"name": "More countries: findahelpline.com", "number": ""},
]
CRISIS_REPLY = ("I'm really concerned about what you just shared, and I'm glad you told me. You deserve support right now, "
                "and you don't have to carry this alone. Please reach out to one of the helplines below, or tell someone you "
                "trust (a friend, family member, or counsellor) to be with you. If you are in immediate danger, call your "
                "local emergency number now.")

def is_crisis(text):
    """Normalize apostrophes and check if input matches any crisis regex pattern."""
    t = text.lower().replace("\u2019", "'")
    return any(re.search(p, t) for p in CRISIS)

# ---------- 2. EMOTION + INTENT DETECTION (lexicon NLP; Gemini also classifies when enabled) ----------
# LEX: Stores an emotional lexicon of words and phrases associated with everyday stress, anxiety, or low mood.
# Used to classify user sentiment and provide supportive, empathetic responses for non-crisis distress.
LEX = {
    "joy": ["happy", "glad", "great", "excited", "proud", "grateful", "good", "wonderful", "amazing", "relieved", "cheerful", "love", "awesome", "fun", "better"],
    "sadness": ["sad", "depress", "cry", "hopeless", "empty", "down", "miserable", "grief", "heartbroken", "worthless", "unhappy", "low", "numb", "hurt"],
    "anger": ["angry", "mad", "furious", "annoy", "hate", "irritat", "frustrat", "rage", "unfair", "resent"],
    "anxiety": ["anxi", "worr", "panic", "nervous", "scared", "afraid", "fear", "dread", "overthink", "uneasy", "restless", "tense"],
    "stress": ["stress", "overwhelm", "pressure", "exam", "deadline", "burn", "exhaust", "too much", "assignment", "workload", "can't cope", "tired", "struggl"],
    "loneliness": ["lonely", "alone", "isolated", "no friends", "left out", "ignored", "nobody", "homesick", "miss home"],
}
# MOOD: Baseline weighting scores used to rank detected emotional states.
# NEG_POS: Regex pattern to detect negated positive phrases (e.g., "not happy", "no longer fine").
MOOD = {"joy": 5, "neutral": 3, "stress": 2.5, "anxiety": 2.5, "anger": 2, "sadness": 1.5, "loneliness": 1.5, "crisis": 1}
NEG_POS = re.compile(r"(not|n't|never|no longer)\s+(\w+\s+)?(happy|good|great|fine|okay|ok|well)")

def detect(text):
    """Score emotional categories using LEX keywords and handle negated positive words."""
    t = text.lower().replace("\u2019", "'")
    scores = {e: sum(1 for k in kws if re.search(r"\b" + re.escape(k), t)) for e, kws in LEX.items()}
    if NEG_POS.search(t):
        scores["joy"] = 0
        scores["sadness"] += 2
    best, total = max(scores, key=scores.get), sum(scores.values())
    if total == 0:
        return "neutral", 0.5, "chat"
    intent = "seek_advice" if re.search(r"\?|\bhow (do|can|to)\b|\bwhat should\b|\bhelp\b|\badvice\b", t) else "vent"
    return best, round(scores[best] / total, 2), intent

# ---------- 3. CONTENT: CBT replies, coping tools, topics ----------
REPLIES = {
    "joy": ["That's lovely to hear! 🌟 Moments like this are worth noticing. What do you think contributed to feeling this way? Naming it helps you repeat it.",
            "I'm really glad things feel brighter. Take a few seconds to savour it - what exactly is making you smile right now?",
            "Wonderful! Positive moments build resilience. Would you like to note one thing you're proud of today?"],
    "sadness": ["I'm sorry you're feeling low - thank you for sharing it with me. Your feelings are valid. Is there one thought that keeps coming back? Writing it down can make it feel lighter.",
                "That sounds heavy, and you don't have to fix it all right now. What would you say to a close friend who felt exactly this way?",
                "It makes sense to feel down with what you're going through. Let's gently check: is this thought a fact, or a feeling that's just loud right now?"],
    "anger": ["It sounds like something really got to you, and anger is a valid signal. Before reacting, let's pause: what exactly happened, and what do you need right now?",
              "I hear your frustration. Often anger sits on top of hurt or stress. What do you think is underneath it?",
              "That does sound unfair. Let's separate what you can control from what you can't - which part can you act on?"],
    "anxiety": ["Anxiety can feel so intense, but it passes. You're safe in this moment. What is the specific worry, and how likely is it really to happen?",
                "Thank you for telling me. Let's slow things down: what's the worst case, the best case, and the most realistic case?",
                "Racing thoughts are exhausting. Let's bring you back to the present first - then we can look at the worry together."],
    "stress": ["That sounds like a lot to carry. Let's break it down: what is the single most important thing that needs doing first?",
               "Feeling overwhelmed is a sign you've been pushing hard. Which tasks are urgent, and which only feel urgent?",
               "You're handling more than you give yourself credit for. Let's try one small step - what could you do in the next 10 minutes?"],
    "loneliness": ["Feeling alone is painful, and I'm glad you reached out. You matter. Is there one person you could send a small message to today?",
                   "Loneliness is more common than people admit, especially for students. What kind of connection would feel good right now?",
                   "I'm here with you. Let's think about it: is there a thought like 'nobody cares' that we can gently test against the evidence?"],
}
# when the same feeling continues, walk the user through a short CBT ladder instead of repeating
LADDER = [
    "Thank you for opening up more. Let's look at the thought behind this feeling: what exact thought is going through your mind right now? Try to say it in one sentence.",
    "Now let's test that thought like a detective: what evidence supports it, and what evidence goes against it?",
    "If a close friend had this exact thought, what would you tell them? Try saying that same kindness to yourself - what does it sound like?",
    "Let's turn this into a small plan: what is one tiny action (5-10 minutes) that could make today a little lighter?",
    "You've done real work here. Compare how you feel now with when we started - what's one thing you'll take away from this?",
]
EXERCISES = {
    "joy": {"name": "Gratitude Journaling", "type": "text", "steps": ["Write down 3 things that went well today.", "For each, note why it happened.", "Read them back and smile."]},
    "sadness": {"name": "Tiny Joy Activation", "type": "text", "steps": ["Pick one small pleasant action (walk, music, tea).", "Do it for just 10 minutes.", "Rate your mood before and after."]},
    "anger": {"name": "Box Breathing", "type": "breathing", "steps": ["Breathe in for 4 seconds.", "Hold for 4 seconds.", "Breathe out for 4 seconds, hold for 4. Repeat 4 times."]},
    "anxiety": {"name": "5-4-3-2-1 Grounding", "type": "text", "steps": ["Name 5 things you can see.", "4 things you can touch.", "3 things you hear, 2 you smell, 1 you taste."]},
    "stress": {"name": "4-7-8 Breathing", "type": "breathing", "steps": ["Breathe in through the nose for 4 seconds.", "Hold for 7 seconds.", "Exhale slowly for 8 seconds. Repeat 4 times."]},
    "loneliness": {"name": "Reach-Out + Self-Compassion", "type": "text", "steps": ["Send a simple 'thinking of you' message to someone.", "Place a hand on your chest and say 'This is hard, and I'm not alone in feeling it.'"]},
    "neutral": {"name": "1-Minute Mindful Check-in", "type": "text", "steps": ["Close your eyes and take 3 slow breaths.", "Notice your body from head to toe.", "Ask yourself: what do I need right now?"]},
}
SLEEP_EX = {"name": "Wind-Down Routine", "type": "text", "steps": ["Put screens away 30 minutes before bed.", "Write tomorrow's worries on paper to 'park' them.", "Do slow breathing in bed: in 4, out 6, for 5 minutes."]}
FOCUS_EX = {"name": "5-Minute Start Rule", "type": "text", "steps": ["Pick ONE small task.", "Set a timer for 5 minutes and just begin.", "When it rings, decide whether to continue. Starting is the hardest part."]}
KIND_EX = {"name": "Self-Compassion Break", "type": "text", "steps": ["Say: 'This is a moment of struggle.'", "Say: 'Many people feel this way; I'm not alone.'", "Say: 'May I be kind to myself right now.'"]}
TOPICS = {  # keyword -> (regex, reply, default emotion, exercise)
    "sleep": (r"\b(sleep|insomnia|awake all night|nightmare|wake up at night)",
              "Poor sleep and mood affect each other, so it's worth caring for. A few things that help: a steady bedtime, no screens for 30 minutes before bed, and writing your worries on paper so your mind can let go. What usually keeps you awake - racing thoughts, stress, or your routine?",
              "stress", SLEEP_EX),
    "focus": (r"\b(procrastinat|can'?t focus|can'?t concentrate|motivat|lazy|distract|unproductive)",
              "That's very common, and it's usually about feeling overwhelmed, not about being lazy. Try the 5-minute rule: start one small task for just five minutes. What is one task you've been avoiding, and what makes it feel heavy?",
              "stress", FOCUS_EX),
    "selfesteem": (r"\b(not good enough|failure|useless|stupid|hate myself|i suck|worthless|ugly|loser)\b",
                   "I'm sorry you're being so hard on yourself. A harsh inner voice isn't the truth, it's a thought pattern, and thoughts can be questioned. What would you say to a friend who spoke about themselves like this? If these thoughts feel overwhelming, please talk to someone you trust or call Tele-MANAS at 14416.",
                   "sadness", KIND_EX),
    "relationship": (r"\b(breakup|broke up|girlfriend|boyfriend|relationship|argument|fight with|my parents|my family|roommate)\b",
                     "Relationships can bring up some of our strongest feelings. Thank you for sharing this. What happened, and how did it leave you feeling inside?",
                     "sadness", EXERCISES["neutral"]),
}
PROBES = ["On a scale of 1 to 10, how is your mood right now, and what is behind that number?",
          "What was the hardest moment of your day so far?",
          "How have you been sleeping and eating lately?",
          "Is there something coming up, like an exam, project or conversation, that is on your mind?",
          "What is one thing that went okay today, even something small?"]
GENERAL = ["Thanks for sharing that with me. I'd like to understand how it's affecting you - if you had to name the feeling behind it in one word, what would it be?",
           "I hear you. How did that leave you feeling, emotionally and in your body (tense, tired, restless, heavy)?",
           "That helps me understand your day. Which part of it has been weighing on you the most?"]
OFFTOPIC = "I'm best at supporting your emotional wellbeing, so I can't help much with that one. 🙂 But I'd love to know how you're doing - how has your mood been today?"
SMALL = {
    "howru": ["I'm here and ready to listen, thanks for asking 💙 But I'd love to hear about you - how are you really feeling today?"],
    "thanks": ["You're very welcome! 💙 Looking after your mind matters. Is there anything else on your heart, or would you like to try a short calming exercise?"],
    "bye": ["Take care of yourself 🌿 You can come back anytime. If things ever feel too heavy, Tele-MANAS (14416) is available 24/7."],
    "about": ["I'm MindEase, an AI companion that uses CBT and mindfulness ideas to support your emotional wellbeing. I'm not a therapist, but I'm a private, judgement-free place to talk. What's on your mind today?"],
    "help": ["I can listen, help untangle worries with CBT-style questions, suggest breathing and grounding exercises, and track your mood over time. A good start: tell me how your day has been, or what you're feeling right now."],
    "talk": ["Of course, I'm all ears. 💙 You can start anywhere: what's been weighing on you, or how you've been feeling lately?"],
    "exercise": ["Sure! I've put a calming breathing exercise in the Coping tool card. Try it for a minute or two, then tell me how it felt."],
    "yes": ["Okay 🙂 Tell me a little more - what has been on your mind lately?"],
    "no": ["That's okay, there's no pressure. What would feel most helpful right now: talking things through, or a quick calming exercise?"],
    "idk": ["That's completely okay, feelings aren't always easy to name. Let's try: is your body feeling tense, tired or restless? Or is your mind busy, heavy or numb?"],
}
INTRO = ("Hi there! 💙 I'm MindEase, a private space to talk about how you feel. I can help with stress, anxiety, low mood, loneliness, "
         "sleep, exam pressure and more. To begin: how has your day been, on a scale of 1 to 10, and what is behind that number?")
AGAIN = ["Hello again! 😊 I'm glad you're here. How are you feeling right now?", "Hey, welcome back 💙 What's on your mind at the moment?"]

def small_talk(t):
    rules = [("exercise", r"\b(exercise|breathing|calm me|relax)\b"), ("howru", r"how are you|how r u|how'?s it going|what'?s up|wassup"),
             ("thanks", r"\b(thanks|thank you|thx|thank u)\b"), ("bye", r"\b(bye|goodbye|see you|see ya|good night|gtg|talk later)\b"),
             ("about", r"who are you|what are you|your name|are you (a )?(bot|real|human|ai|robot)|who made you"),
             ("talk", r"need to talk|can we talk|want to talk|someone to talk|talk to someone|just talk"),
             ("help", r"what can you do|^help( me)?[\s!.?]*$|how does this work|where do i start|what do i (say|do)"),
             ("greet", r"^(hi+|hello+|hey+|heya|hola|namaste|yo|good (morning|afternoon|evening))\b"),
             ("fine", r"^(i'?m |im |i am |feeling |it'?s )?(fine|ok|okay|alright|good|not bad|so so|meh|normal|nothing much|same|great)[\s!.]*$"),
             ("idk", r"\b(idk|i don'?t know|dunno|not sure|no idea|can'?t explain|hard to say)\b"),
             ("yes", r"^(yes|yeah|yep|yup|sure|please|go ahead)[\s!.]*$"), ("no", r"^(no|nope|nah|not really|nothing)[\s!.]*$")]
    return next((k for k, rx in rules if re.search(rx, t)), None)

def fresh(options, used):
    left = [o for o in options if o not in used]
    return random.choice(left or options)

# ---------- 4. DATABASE: mood log + feedback (anonymous ids only) ----------
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS moods(id INTEGER PRIMARY KEY, uid TEXT, ts REAL, emotion TEXT, score REAL)")
        c.execute("CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, uid TEXT, key TEXT, rating INTEGER)")

def recent_emotion(uid):  # the user's emotion from the last 30 minutes, to keep the conversation going
    with db() as c:
        r = c.execute("SELECT emotion, ts FROM moods WHERE uid=? ORDER BY ts DESC LIMIT 1", (uid,)).fetchone()
    return r["emotion"] if r and time.time() - r["ts"] < 1800 and r["emotion"] not in ("crisis", "neutral") else None

def pick_reply(emotion, used):
    """Feedback loop: replies with more thumbs-up are chosen more often; already-used replies are avoided."""
    opts = REPLIES[emotion]
    idx = [i for i, r in enumerate(opts) if r not in used] or list(range(len(opts)))
    with db() as c:
        w = [max(0.2, 1 + 0.5 * c.execute("SELECT COALESCE(SUM(rating),0) FROM feedback WHERE key=?", (f"{emotion}:{i}",)).fetchone()[0]) for i in idx]
    i = random.choices(idx, weights=w)[0]
    return i, opts[i]

# ---------- 5. GEMINI (free tier) ----------
SYSTEM = """You are MindEase, a warm, caring mental wellness companion for students and young adults, inside an app that offers private 24/7 emotional support.
RULES:
- Your ONLY topic is emotional wellbeing: feelings, stress, anxiety, mood, sleep, loneliness, relationships, motivation, self-esteem, study pressure and coping skills. If the user asks about something unrelated, kindly say it is outside your focus and gently bring the conversation back to how they are feeling.
- Never get stuck on greetings. If the user says hi or hello, greet them warmly in one sentence, say briefly what you can help with, and ask ONE open question such as how their day or mood has been (for example on a scale of 1 to 10).
- Always move the conversation forward: validate the feeling, then use ONE CBT or mindfulness technique (thought challenging, reframing, behavioural activation, grounding, breathing, self-compassion), then ask ONE gentle follow-up question. Use the earlier messages for context and never repeat yourself.
- Write 2 to 5 short sentences in plain text only (no markdown, no lists, no asterisks), friendly tone, at most one emoji.
- You are not a therapist: never diagnose and never recommend medication. For serious distress, encourage talking to a trusted person or a counsellor.
- If the user mentions suicide, self-harm or being in danger, set risk to "high".
Respond ONLY with JSON in this exact shape: {"emotion": "<joy|sadness|anger|anxiety|stress|loneliness|neutral>", "risk": "<none|high>", "reply": "<your reply>"}"""
SAFETY = [{"category": c, "threshold": "BLOCK_ONLY_HIGH"} for c in
          ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")]

def http_json(url, body=None, timeout=20):
    req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "x-goog-api-key": API_KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def discover():  # if every default model name is retired, ask Google which Flash models exist
    try:
        out = []
        for m in http_json(f"{GEM}/models?pageSize=200").get("models", []):
            n = m.get("name", "").replace("models/", "")
            if "flash" in n and "generateContent" in m.get("supportedGenerationMethods", []) and not any(x in n for x in ("image", "tts", "audio", "live", "embed", "vision", "exp")):
                out.append(n)
        return sorted(out, reverse=True)
    except Exception:
        return []

def candidates():
    c = [m for m in ([PREFERRED, STATE["model"]] + DEFAULT_MODELS) if m and m not in BAD]
    return list(dict.fromkeys(c)) or [m for m in discover() if m not in BAD]

def parse_llm(txt):
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    try:
        d = json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        d = json.loads(m.group()) if m else None
    if not isinstance(d, dict) or not isinstance(d.get("reply"), str) or not d["reply"].strip():
        return None
    emo = str(d.get("emotion", "neutral")).lower()
    return {"reply": re.sub(r"[*_`#]+", "", d["reply"]).strip()[:900], "emotion": emo if emo in EXERCISES else "neutral",
            "risk": "high" if str(d.get("risk", "")).lower() == "high" else "none"}

def ask_gemini(text, history):
    """Returns {'reply','emotion','risk'} or None (then the built-in engine answers)."""
    if not API_KEY:
        return None
    contents = []
    for m in history[-8:]:
        role, c = ("user" if m.get("role") == "user" else "model"), m.get("content")
        if isinstance(c, str) and c.strip():
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"][0]["text"] += "\n" + c[:1000]
            else:
                contents.append({"role": role, "parts": [{"text": c[:1000]}]})
    while contents and contents[0]["role"] != "user":
        contents.pop(0)
    if contents and contents[-1]["role"] == "user":
        contents[-1]["parts"][0]["text"] += "\n" + text
    else:
        contents.append({"role": "user", "parts": [{"text": text}]})
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": contents, "safetySettings": SAFETY,
            "generationConfig": {"temperature": 0.8, "maxOutputTokens": 2048, "responseMimeType": "application/json"}}
    for model in candidates()[:5]:
        try:
            data = http_json(f"{GEM}/models/{model}:generateContent", body)
            parts = data["candidates"][0]["content"]["parts"]
            res = parse_llm("".join(p.get("text", "") for p in parts if not p.get("thought")))
            if res:
                STATE.update(model=model, error="")
                return res
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")[:200]
            if e.code in (401, 403) or (e.code == 400 and "API key" in msg):
                STATE["error"] = "API key invalid or not allowed - check your .env"
                break
            if e.code == 404:
                BAD.add(model)
            STATE["error"] = f"{model}: HTTP {e.code}" + (" (free quota reached, try again shortly)" if e.code == 429 else "")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            STATE["error"] = f"Cannot reach Gemini ({getattr(e, 'reason', e)})"
            break
        except Exception:  # blocked / malformed answer -> try next model
            STATE["error"] = f"{model}: unusable response"
    if STATE["error"]:
        print("[Gemini]", STATE["error"], "- using built-in replies")
    return None

# ---------- 6. BUILT-IN DIALOGUE ENGINE (works with no API key) ----------
def fallback(text, history, emotion, conf, intent, prev):
    """returns (reply, emotion, exercise, log_mood, key, confidence)"""
    t = text.lower().replace("\u2019", "'").strip()
    used = {m.get("content") for m in history if m.get("role") == "assistant"}
    turn = sum(1 for m in history if m.get("role") == "user")
    st = small_talk(t) if len(t.split()) <= 7 and emotion == "neutral" else None
    if st == "greet":
        return (INTRO if turn == 0 else fresh(AGAIN, used)), "neutral", EXERCISES["neutral"], False, "chat", conf
    if st == "fine":
        return "Glad it's not too rough. 🙂 Sometimes 'fine' hides a little more. " + fresh(PROBES, used), "neutral", EXERCISES["neutral"], False, "chat", conf
    if st == "idk":
        return fresh(SMALL["idk"] + PROBES, used), "neutral", EXERCISES["neutral"], False, "chat", conf
    if st:
        return random.choice(SMALL[st]), "neutral", EXERCISES["stress" if st == "exercise" else "neutral"], False, "chat", conf
    topic = next((k for k, v in TOPICS.items() if re.search(v[0], t)), None)
    if topic and (emotion == "neutral" or topic in ("sleep", "focus", "selfesteem")):
        _, reply, demo, ex = TOPICS[topic]
        return reply, (demo if emotion == "neutral" or topic == "selfesteem" else emotion), ex, True, f"topic:{topic}", conf
    if emotion == "neutral" and re.search(r"\b(capital of|weather|python|code|solve|recipe|movie|score|news|stock|cricket)\b", t):
        return OFFTOPIC, "neutral", EXERCISES["neutral"], False, "chat", conf
    if emotion != "neutral":
        if prev == emotion:
            return LADDER[sum(1 for u in used if u in LADDER) % len(LADDER)], emotion, EXERCISES[emotion], True, "ladder", conf
        i, reply = pick_reply(emotion, used)
        return reply, emotion, EXERCISES[emotion], True, f"{emotion}:{i}", conf
    if prev:  # user keeps talking about the earlier feeling without using emotion words
        return LADDER[sum(1 for u in used if u in LADDER) % len(LADDER)], prev, EXERCISES[prev], False, "ladder", 0.6
    return fresh(GENERAL + PROBES, used), "neutral", EXERCISES["neutral"], False, "chat", conf

# ---------- 7. PIPELINE ----------
def crisis_result(uid, who="keyword scan"):
    with db() as c:
        c.execute("INSERT INTO moods(uid, ts, emotion, score) VALUES(?,?,?,?)", (uid, time.time(), "crisis", MOOD["crisis"]))
    stages = [("Safety check", f"⚠ HIGH RISK ({who})"), ("Emotion detection", "skipped"), ("Response", "helpline escalation"),
              ("Coping tool", "helplines shown"), ("Mood log", "saved")]
    return {"reply": CRISIS_REPLY, "emotion": "crisis", "confidence": 1.0, "intent": "crisis", "crisis": True, "helplines": HELPLINES,
            "exercise": None, "score": MOOD["crisis"], "key": "crisis", "stages": [{"name": n, "result": r} for n, r in stages]}

def chat(uid, text, history):
    history = [m for m in history if isinstance(m, dict)]
    if is_crisis(text):
        return crisis_result(uid)
    emotion, conf, intent = detect(text)
    prev = recent_emotion(uid)
    res = ask_gemini(text, history)
    if res and res["risk"] == "high":
        return crisis_result(uid, "Gemini")
    if res:
        emotion, reply, conf, log, key = res["emotion"], res["reply"], 0.9, res["emotion"] != "neutral", f"{res['emotion']}:llm"
        ex, src = EXERCISES[emotion], f"Gemini ({STATE['model']})"
    else:
        reply, emotion, ex, log, key, conf = fallback(text, history, emotion, conf, intent, prev)
        src = "built-in CBT dialogue" + (" (Gemini unavailable)" if API_KEY else "")
    if log:
        with db() as c:
            c.execute("INSERT INTO moods(uid, ts, emotion, score) VALUES(?,?,?,?)", (uid, time.time(), emotion, MOOD[emotion]))
    emo_txt = "no strong emotion yet" if emotion == "neutral" else f"{emotion} ({int(conf * 100)}%) · {intent}"
    stages = [("Safety check", "clear ✓"), ("Emotion detection", emo_txt), ("Response", src), ("Coping tool", ex["name"]),
              ("Mood log", "saved" if log else "skipped (no emotion)")]
    return {"reply": reply, "emotion": emotion, "confidence": conf, "intent": intent, "crisis": False, "helplines": [],
            "exercise": ex, "score": MOOD[emotion], "key": key, "stages": [{"name": n, "result": r} for n, r in stages]}

# ---------- HTTP SERVER ----------
STATIC = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
          "/style.css": ("style.css", "text/css"), "/script.js": ("script.js", "application/javascript")}
UID = re.compile(r"[A-Za-z0-9_-]{6,64}")

class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        try:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in STATIC:
            name, ctype = STATIC[u.path]
            with open(os.path.join(BASE, "static", name), "rb") as f:
                return self.send(200, f.read(), ctype)
        if u.path == "/api/status":
            return self.send(200, {"llm": bool(API_KEY), "model": STATE["model"], "error": STATE["error"]})
        if u.path == "/api/moods":
            uid = parse_qs(u.query).get("uid", [""])[0]
            if not UID.fullmatch(uid):
                return self.send(400, {"error": "bad uid"})
            with db() as c:
                rows = c.execute("SELECT ts, emotion, score FROM moods WHERE uid=? ORDER BY ts DESC LIMIT 20", (uid,)).fetchall()
            return self.send(200, {"moods": [dict(r) for r in rows][::-1]})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        d, path = self.body(), urlparse(self.path).path
        uid = str(d.get("uid", ""))
        if not UID.fullmatch(uid):
            return self.send(400, {"error": "bad uid"})
        if path == "/api/chat":
            text = str(d.get("message", "")).strip()[:1000]
            if not text:
                return self.send(400, {"error": "empty message"})
            hist = d.get("history", [])
            return self.send(200, chat(uid, text, hist if isinstance(hist, list) else []))
        if path == "/api/feedback":
            with db() as c:
                c.execute("INSERT INTO feedback(uid, key, rating) VALUES(?,?,?)", (uid, str(d.get("key", ""))[:40], 1 if d.get("rating") == 1 else -1))
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})

    def do_DELETE(self):  # privacy: user can erase all their data
        uid = parse_qs(urlparse(self.path).query).get("uid", [""])[0]
        if not UID.fullmatch(uid):
            return self.send(400, {"error": "bad uid"})
        with db() as c:
            c.execute("DELETE FROM moods WHERE uid=?", (uid,))
            c.execute("DELETE FROM feedback WHERE uid=?", (uid,))
        self.send(200, {"ok": True})

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    init_db()
    print(f"MindEase running at http://localhost:{PORT}")
    print("AI replies: " + ("Gemini ENABLED (free tier)" if API_KEY else "OFF - paste your key into api_key.txt (built-in CBT dialogue is used meanwhile)"))
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
