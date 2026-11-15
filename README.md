# MindEase - Mental Wellness AI Chatbot

## Run from scratch
1. Install Python 3.8+ from https://www.python.org/downloads (tick "Add Python to PATH" on Windows). Check with `python --version`.
2. Unzip the project and open a terminal inside the `wellness` folder.
3. Get a FREE Gemini key (no card): https://aistudio.google.com/apikey -> "Create API key" -> copy it.
4. Open `api_key.txt`, delete the placeholder, paste your key, save.
5. Run `python app.py` (on Mac/Linux use `python3 app.py`).
6. Open http://localhost:8000 - the header badge should say "Gemini AI".

No key? It still works with the built-in CBT dialogue (badge: Offline mode).
Stop the server with Ctrl+C. Change port: `PORT=9000 python app.py`.

## Pipeline
User input -> Safety check -> Emotion detection -> Response (Gemini or built-in CBT) -> Coping tool + Mood log -> Feedback

## Files
- app.py - backend (server, pipeline, Gemini client, SQLite)
- static/index.html, style.css, script.js - frontend
- api_key.txt - paste your free key here
- .env.example - optional alternative (rename to .env)
## Safety Layer 
- This application includes a built-in safety layer designed to identify signs of emotional distress and acute crisis in user inputs. By matching incoming text against predefined keyword lists (CRISIS) and emotional lexicons (LEX), the system flags high-risk phrases and triggers appropriate supportive responses. This ensures that urgent mental health expressions are detected immediately before standard processing takes place. 
## Testing

To verify the safety layer and emotion detection locally, run python app.py and test the following sample inputs at http://localhost:8000:

* *Crisis detection:* "I don't want to live anymore" — verifies that high-risk phrases immediately trigger the emergency helpline response.
* *Stress & emotion detection:* "I'm so stressed about my exams" — verifies that everyday academic stress is classified accurately and receives a supportive response.
* *Negated positive phrases:* "I am not happy anymore" — verifies that negation handling (NEG_POS) prevents false positive joy classification.
*