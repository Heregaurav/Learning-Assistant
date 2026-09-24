# AI Learning Assistant (FLAM frontend assignment)

Topic or notes in, structured lesson out: explanation, flashcards, quiz, evaluation, saved history. Not a chatbot.

## Run
```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env   # fill in the keys
uvicorn main:app --reload
# frontend
cd frontend && cp .env.example .env && npm install && npm run dev
```
LLM providers: Groq, Google Gemini, and OpenRouter free models can be selected in the Learn screen. Set `GROQ_API_KEY`, `GEMINI_API_KEY`, and/or `OPENROUTER_API_KEY` in `backend/.env`; keys are used only by the backend.
Google sign-in: create a Google OAuth **Web application** client in Google Cloud Console, add `http://localhost:5173` and `http://127.0.0.1:5173` to authorized JavaScript origins, then put the same client ID in `backend/.env` as `GOOGLE_CLIENT_ID` and `frontend/.env` as `VITE_GOOGLE_CLIENT_ID`. The first Google sign-in creates the user's profile; sessions, topics, quiz progress, and history are scoped to that Google account.
MongoDB Atlas: create a free cluster, add a database user, allow your IP, paste the connection string into `MONGODB_URI`.
Collections (`users`, `sessions`, `topics`) and the `demo-user` are created automatically.

## How bad AI output is handled
Backend: JSON parse, Pydantic schema (including "correctAnswer must be one of options"), typed errors
(`invalid_json`, `bad_schema`, `empty`, `timeout`, `llm_failed`). Frontend: shape check again in `lib/validate.ts`
before render, request-id guard against stale responses, abort + 70s timeout, retry buttons, error boundary.

## Progress
Session score = correct / total. Topic progress = mean of its completed session scores. Stats are recomputed from stored sessions.

## Status / next
Done: learn flow, validation, persistence, history, reopen session, all API endpoints (profile, topics, graph included).
Not yet built in the UI: dashboard, profile page, React Flow graph + topic panel, retest mistakes.

## AI usage / time spent
Fill in honestly before submitting.
