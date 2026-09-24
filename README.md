# AI Learning Assistant

An AI-powered study app that turns a topic, note, or lecture summary into a structured learning lesson with explanations, flashcards, quizzes, scoring, and progress tracking.

This project is built as a full-stack app:
- Frontend: React + TypeScript + Vite
- Backend: FastAPI (Python)
- Database: MongoDB Atlas
- Authentication: Google OAuth
- AI providers: Groq, Google Gemini, and OpenRouter

## What the app does

Users can:
- sign in with Google
- enter any topic or notes they want to study
- generate a lesson with:
  - topic overview
  - structured explanations
  - flashcards
  - quiz questions
- complete the quiz and receive a score
- track their progress across sessions and topics
- view learning history and profile statistics

## Tech stack

- Frontend: React, TypeScript, Vite, React Router
- Backend: Python, FastAPI, Pydantic
- Database: MongoDB
- AI: OpenAI-compatible APIs via Groq, Gemini, and OpenRouter
- Auth: Google OAuth 2.0

## Project structure

```text
CURIOSITY/
├── backend/
│   ├── main.py
│   ├── models.py
│   ├── llm.py
│   └── requirements.txt
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── App.tsx
│       ├── main.tsx
│       ├── styles.css
│       ├── types.ts
│       ├── components/
│       ├── lib/
│       └── pages/
├── .gitignore
├── README.md
└── .venv/   (local, optional)
```

## Prerequisites

Before running the app, make sure you have:
- Python 3.10+
- Node.js 18+
- npm
- MongoDB Atlas account or a local MongoDB instance
- Google Cloud OAuth credentials
- at least one LLM API key from Groq, Gemini, or OpenRouter

## Backend setup

From the project root:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a file named `.env` inside `backend/` with values like:

```env
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster-url>/<database>?retryWrites=true&w=majority
DATABASE_NAME=learning_assistant
GOOGLE_CLIENT_ID=<your-google-oauth-client-id>
GROQ_API_KEY=<your-groq-key>
# or
# GEMINI_API_KEY=<your-gemini-key>
# or
# OPENROUTER_API_KEY=<your-openrouter-key>
```

Notes:
- The app accepts Groq, Gemini, or OpenRouter as the AI provider.
- The backend reads the provider key from the environment.
- If you use Groq and want to override the default key name, the project also supports `LLM_API_KEY`.

Then run the backend:

```bash
cd backend
source .venv/bin/activate
uvicorn main:app --reload
```

The API runs on:
- http://localhost:8000

## Frontend setup

Open a new terminal and run:

```bash
cd frontend
npm install
```

Create a `.env` file in `frontend/`:

```env
VITE_GOOGLE_CLIENT_ID=<your-google-oauth-client-id>
```

Then start the frontend:

```bash
cd frontend
npm run dev
```

The app is available at:
- http://localhost:5173

## Google OAuth setup

1. Go to Google Cloud Console
2. Create a Google OAuth 2.0 client ID
3. Use the following authorized JavaScript origins:
   - http://localhost:5173
   - http://127.0.0.1:5173
4. Add the same client ID to both:
   - backend/.env as `GOOGLE_CLIENT_ID`
   - frontend/.env as `VITE_GOOGLE_CLIENT_ID`

On first login, the app creates the user profile in MongoDB and stores session/topic data under that Google account.

## MongoDB setup

1. Create a MongoDB Atlas cluster
2. Create a database user
3. Allow your IP address
4. Copy the connection string into `backend/.env` as `MONGODB_URI`

The app uses collections such as:
- `users`
- `sessions`
- `topics`

## Core backend behavior

The backend exposes endpoints for:
- Google auth: `/api/auth/google`
- health check: `/api/health`
- lesson generation: `/api/learn`
- session completion: `/api/sessions/{sid}/complete`
- session list: `/api/sessions`
- profile: `/api/profile`
- topics: `/api/topics`
- topic detail: `/api/topics/{tid}`
- graph data: `/api/graph`

The lesson generator validates AI output and repairs malformed responses before returning structured content. It checks for JSON validity, schema correctness, answer-option matching, and quiz quality.

## App flow

1. User signs in with Google
2. User enters a topic or notes
3. Backend calls the selected LLM provider
4. AI returns structured lesson content
5. App shows explanation, flashcards, and quiz
6. User answers questions and gets score results
7. Session results and topic progress are saved to MongoDB
8. User can revisit history and profile data later

## Notes

- This app is not a chatbot; it is a guided learning assistant.
- The AI output is intended to be structured educational content, not conversational responses.
- Session scores are computed as correct answers divided by total questions.
- Topic progress is based on the average score of completed sessions for that topic.

## Common commands

```bash
# backend
cd backend
source .venv/bin/activate
uvicorn main:app --reload

# frontend
cd frontend
npm run dev
```

