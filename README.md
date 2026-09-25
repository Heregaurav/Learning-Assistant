# Curiosity: AI Study Assistant

Curiosity is a full-stack study assistant for turning a topic, pasted notes, or a lecture summary into an interactive learning session. A generated session combines a structured explanation, optional visual study blocks, flashcards, and a quiz. Completed work is saved to MongoDB so learners can return to sessions, review progress, and retest a topic.

The project is designed around a focused learning loop rather than an open-ended chatbot:

1. Sign in with Google or choose Guest Mode.
2. Enter a topic or paste study material.
3. Generate a structured lesson with the selected AI provider.
4. Read the explanation and inspect generated cards, checklists, or charts.
5. Flip through flashcards.
6. Take the quiz and receive a score with explanations for missed questions.
7. Refine the saved lesson with a follow-up instruction.
8. Retest a topic with the original questions plus three additional AI-generated questions.
9. Reopen the saved session from History or continue from Profile.

## Features

### Lesson generation

The learner can submit a short topic or up to 20,000 characters of notes. The backend asks the selected provider for a structured JSON lesson and validates the response before it reaches the UI.

### Document learning

Attach a PDF, DOCX, PPTX, TXT, or Markdown file using the **+** button in the Learn composer. Files are limited to 12 MB. The backend extracts and chunks the document, then uses its content as the source for a lesson with the same explanations, flashcards, and quiz as topic learning. Scanned PDFs are processed with local OCR, up to 20 pages. Document sessions are saved with their source metadata and appear in History.

Generated lesson content includes:

- A topic title and overview.
- Explanation sections with examples.
- Key takeaways.
- Common mistakes.
- Flashcards with questions and answers.
- Multiple-choice quiz questions with four options and explanations.
- Optional typed content blocks:
  - `card`: a highlighted idea or definition.
  - `checklist`: actionable items rendered as a checklist.
  - `chart`: labels and numeric values rendered as a compact bar chart.

Generation is exposed through an SSE endpoint. The UI receives progress stages such as `understanding`, `building`, and `ready`, then receives the saved lesson payload.

### Practice and assessment

- Flashcards can be flipped and navigated with Previous and Next controls.
- Quiz options provide immediate correctness feedback.
- Completed quizzes show the score and questions that need review.
- Answers and completion data are persisted with the session.
- Topic progress is calculated from completed sessions for that topic.

### Retesting

Each topic supports up to three retests. A retest:

- Keeps the previous quiz questions.
- Adds exactly three newly generated questions.
- Creates a separate saved session.
- Uses prior question text to reduce repetition.
- Updates the topic's session history and progress after completion.

The limit is enforced in the backend, not only in the UI. After three retests, the action is disabled and a fourth API request is rejected without calling the AI provider.

### Refinement

While viewing a lesson, the learner can submit a follow-up prompt such as:

- `Make the explanation simpler.`
- `Add a practical example.`
- `Turn the key ideas into a checklist.`

The backend sends the existing lesson and refinement instruction to the AI. The result is merged with the saved lesson, validated, and written back to the same session. Explanation, flashcards, quizzes, and content blocks all update together.

### Persistence and reload behavior

- Session routes such as `/session/{id}` load their data from MongoDB on every visit.
- History and Profile reload their data from the backend.
- The active lesson on the root Learn page is cached locally so a browser reload does not immediately discard the generated lesson.
- Refined active lessons update that local cache as well.
- The active local lesson is removed on sign-out.

### Guest Mode

Guest Mode is intended for trying the learning workflow without creating or connecting a Google account. The browser creates a random `guest_<uuid>` identifier and sends it in the `X-Guest-ID` header. The backend uses that identifier to isolate the guest's temporary sessions, topics, quiz results, refinement requests, and retests.

Guest users can use the core learning flow, including lesson generation, flashcards, quizzes, refinement, retesting, History, and Profile. If a guest profile or history request is unavailable, the frontend shows a useful empty guest workspace instead of a blocking authentication error.

Guest data is browser-scoped rather than account-scoped. Clearing browser storage, changing browsers, or using another device loses access to that guest workspace. Choose Google login for a named profile, durable account-based history, and a better long-term experience.

### Interface and accessibility

- Responsive layouts for desktop and phone-sized screens.
- Authenticated mobile header with a logo, navigation links, mode controls, pause/play control, and profile action.
- Cinematic video background with a plain-background toggle.
- Reduced-motion handling through `prefers-reduced-motion` CSS rules.
- Visible keyboard focus states.
- Left/right arrow navigation between lesson tabs.
- Semantic tab, radio, form, button, and status attributes where appropriate.

## Technology stack

### Frontend

- React 18.
- TypeScript.
- Vite.
- React Router.
- Framer Motion for landing-page and content animations.
- Lucide React for interface icons.
- Tailwind CSS and a project stylesheet for layout and visual styling.

### Backend

- Python.
- FastAPI and Uvicorn.
- Pydantic 2 for request and lesson validation.
- PyMongo for MongoDB access.
- `python-dotenv` for local environment configuration.
- Google Auth libraries for validating Google identity tokens.
- OpenAI-compatible client calls for Groq, Google Gemini, and OpenRouter.

### Data services

- MongoDB Atlas or a local MongoDB deployment.
- Google OAuth 2.0 for authentication.
- One or more supported AI providers:
  - Groq.
  - Google Gemini through its OpenAI-compatible endpoint.
  - OpenRouter through its OpenAI-compatible endpoint.


## Repository structure

```text
CURIOSITY/
├── backend/
│   ├── main.py              # FastAPI app, authentication, persistence, routes
│   ├── models.py            # Pydantic request and lesson models
│   ├── llm.py               # Provider clients, prompts, normalization, validation
│   ├── requirements.txt     # Python dependencies
│   ├── .env.example         # Environment variable template
│   └── .venv/               # Local virtual environment, not required in git
├── frontend/
│   ├── index.html            # HTML entry point and favicon
│   ├── package.json          # npm scripts and dependencies
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── App.tsx           # Authenticated shell and application routes
│       ├── main.tsx          # React entry point
│       ├── styles.css        # Global, responsive, and authenticated styles
│       ├── types.ts          # Frontend lesson and block types
│       ├── components/
│       │   ├── Lesson.tsx    # Explanation, blocks, flashcards, quiz, refine UI
│       │   └── States.tsx    # Loading, error, empty, and error-boundary states
│       ├── lib/
│       │   ├── api.ts        # Authenticated API client and SSE reader
│       │   └── validate.ts   # Runtime validation before rendering AI data
│       └── pages/
│           ├── Landing.tsx
│           ├── Learn.tsx
│           ├── Session.tsx
│           ├── History.tsx
│           └── Profile.tsx
├── README.md
└── .gitignore
```

## Prerequisites

Install the following before setup:

- Python 3.10 or newer. The current development environment uses Python 3.12.
- Node.js 18 or newer.
- npm.
- A MongoDB Atlas cluster or local MongoDB server.
- A Google Cloud OAuth client ID.
- At least one supported AI provider key.

The app needs a database and an AI key to perform the guest learning workflow. Google OAuth is additionally required for named sign-in, account-based persistence, and the full personal experience. The frontend can install and build without active backend credentials, but lesson generation still requires a configured backend and AI provider key.

## Installation

### 1. Clone and enter the project

```bash
git clone <repository-url>
cd CURIOSITY
```

### 2. Create the backend environment

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Configure backend environment variables

Copy the example file:

```bash
cp backend/.env.example backend/.env
```

Then edit `backend/.env`:

```env
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster>/<database>?retryWrites=true&w=majority
DATABASE_NAME=learningAssistant

GOOGLE_CLIENT_ID=<google-oauth-client-id>

# Configure at least one provider.
GROQ_API_KEY=<groq-api-key>
# GEMINI_API_KEY=<gemini-api-key>
# OPENROUTER_API_KEY=<openrouter-api-key>

# Optional Groq compatibility settings.
# LLM_API_KEY=<groq-api-key>
# LLM_MODEL=qwen/qwen3.8-27b
# LLM_BASE_URL=https://api.groq.com/openai/v1

GOOGLE_CLOCK_SKEW_SECONDS=300
FRONTEND_ORIGINS=http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174
```

Never commit `backend/.env`. It contains database credentials, OAuth configuration, and AI provider secrets. Use `.env.example` for shareable configuration documentation.

### 4. Install frontend dependencies

Open a second terminal from the project root:

```bash
cd frontend
npm install
```

Create `frontend/.env`:

```env
VITE_GOOGLE_CLIENT_ID=<same-google-oauth-client-id>
```

The frontend API base defaults to `http://localhost:8000`. To use another backend address, define:

```env
VITE_API_BASE_URL=http://localhost:8000
```

## Google OAuth configuration

Google login is optional for trying the app as a guest, but it is recommended for a durable personal workspace.

1. Open Google Cloud Console.
2. Create or select a project.
3. Configure the OAuth consent screen.
4. Create an OAuth 2.0 Web application client.
5. Add the local frontend origins to Authorized JavaScript origins:
   - `http://localhost:5173`
   - `http://localhost:5174`
   - `http://127.0.0.1:5173`
   - `http://127.0.0.1:5174`
6. Put the client ID in both:
   - `backend/.env` as `GOOGLE_CLIENT_ID`.
   - `frontend/.env` as `VITE_GOOGLE_CLIENT_ID`.

The backend validates the Google identity token, creates or updates the user record, and uses the Google subject ID as the MongoDB user identifier. The frontend stores the returned credential in browser local storage for subsequent API calls.

## MongoDB configuration

For MongoDB Atlas:

1. Create a cluster.
2. Create a database user.
3. Add the development machine's IP address to the network access list.
4. Copy the connection string into `MONGODB_URI`.
5. URL-encode special characters in the database username or password.

The application creates and uses these collections:

- `users`: Google identity and aggregate statistics.
- `sessions`: generated lessons, quiz answers, scores, retests, and timestamps.
- `topics`: topic-level progress and references to session IDs.

No migration command is required for the current document model. New fields are added defensively when new sessions or requests are handled, and older lesson documents remain readable through validation and normalization.

## Running the application

Start the backend:

```bash
cd backend
source .venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Start the frontend in another terminal:

```bash
cd frontend
npm run dev
```

Vite normally serves the frontend at `http://localhost:5173`. If that port is busy, Vite may choose `http://localhost:5174`; add that origin to Google OAuth and `FRONTEND_ORIGINS` as needed.

Useful URLs:

- Frontend: `http://localhost:5173` or the Vite fallback port.
- Backend health check: `http://localhost:8000/api/health`.
- FastAPI documentation: `http://localhost:8000/docs`.

## User guide

### Choose an account mode

The landing page provides two paths:

- **Login with Google**: creates or loads a named user profile and stores progress under that Google account.
- **Use as guest**: opens a temporary browser-scoped workspace immediately without Google authentication.

The UI labels the authenticated header accordingly. Guest mode shows `Guest mode` and `Login for more`; Google mode shows the user's name and sign-out action.

Log in for saved account history, a named profile, and a better experience when returning from another browser or device. Use Guest Mode when you want to explore the lesson workflow quickly.

### Generate a lesson

1. Open the frontend.
2. Choose Login or Use as guest.
3. On Learn, enter a topic or paste notes.
4. Select Beginner, Intermediate, or Advanced.
5. Select the AI model.
6. Submit the composer.
7. Watch the generation status move through the streamed stages.

The generated lesson opens with an explanation. The tabs switch between Explanation, Flashcards, and Quiz.

### Use generated blocks

When the model returns blocks, they appear below the explanation:

- Cards show a highlighted idea and supporting text.
- Checklists show actionable items.
- Charts show labeled values as bars.

Blocks are optional. A lesson without valid blocks still renders normally.


### Refine a lesson

Enter a follow-up instruction in the refinement field at the top of a lesson. The refinement is sent with the current saved lesson, not as a new blank generation. When successful, the updated explanation, blocks, flashcards, and quiz replace the current lesson and are saved to the same session.

### Complete a quiz

1. Open the Quiz tab.
2. Select an answer.
3. Read the explanation shown after answering.
4. Move through the questions.
5. Finish the session.

The score, answers, number of reviewed flashcards, and completion timestamp are saved. Reloading the session URL restores the saved result.

### Retest a topic

Use Retest beside a topic in Profile or beside a session in History. A retest creates a new session containing the previous topic questions plus three new questions. A topic may be retested at most three times.

### Reload and revisit

- Use History to reopen saved sessions.
- Use Profile to see topic progress, scores, and retest availability.
- Copy or bookmark a `/session/{id}` URL to reopen a specific saved session.
- Reloading the root Learn page restores the active lesson from local storage.

## API reference

Authenticated application routes accept either a Google bearer token or a valid guest identifier. Google users send:

```http
Authorization: Bearer <google-credential>
```

Guest users send:

```http
X-Guest-ID: guest_<uuid>
```

The backend rejects requests that provide neither credential. Guest and Google data are isolated by their respective user IDs.

### Authentication and health

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/google` | Validate a Google credential and return the signed-in user and token. |
| `GET` | `/api/health` | Check database connectivity. |

### Learning and sessions

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/learn` | Generate and save a lesson as a regular JSON response. |
| `POST` | `/api/learn/stream` | Generate and save a lesson while emitting SSE progress events. |
| `GET` | `/api/sessions` | List the signed-in user's sessions without full lesson payloads. |
| `GET` | `/api/sessions/{sid}` | Load one saved session and its lesson. |
| `POST` | `/api/sessions/{sid}/complete` | Save quiz answers, score, and completion data. |
| `POST` | `/api/sessions/{sid}/refine` | Edit and persist an existing lesson from a follow-up prompt. |

### Topics and profile

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/topics/{tid}/retest` | Create a retest session with previous questions plus three new ones. |
| `GET` | `/api/profile` | Load user details, aggregate stats, strong topics, and review topics. |
| `GET` | `/api/topics` | List topic documents. |
| `GET` | `/api/topics/{tid}` | Load topic progress and completed session history. |
| `GET` | `/api/graph` | Return topic nodes and progress values for graph-style consumers. |

## Architecture and data flow

```text
React/Vite frontend
        |
  | Google bearer token or guest ID + JSON/SSE requests
        v
FastAPI backend
        |
        | validates request and AI output
        +--> OpenAI-compatible provider
        |
        +--> MongoDB users, topics, sessions
```

### AI response safety

The AI is instructed to return JSON only. The backend then:

1. Parses the response.
2. Normalizes sections, flashcards, quizzes, and optional blocks.
3. Ensures quiz answers match one of the options.
4. Validates the result with Pydantic.
5. Performs a repair request when the first response does not satisfy the lesson schema.
6. Returns only validated lesson data to the frontend.

The frontend performs a second runtime validation pass before rendering any AI-generated lesson. Invalid optional blocks are dropped without invalidating the whole lesson.

## AI-usage note

This project uses generative AI as a content-generation and transformation component. The model is used to:

- Convert topics and notes into explanations.
- Create flashcards and multiple-choice questions.
- Produce optional card, checklist, and chart blocks.
- Generate three additional questions for a retest.
- Apply learner-requested refinements to an existing lesson.

The app sends the learner's submitted topic or notes to the selected provider. The provider may process that content according to its own terms, retention policy, and privacy policy. Do not paste confidential, personally identifiable, regulated, or copyrighted material unless you are authorized to send it to the selected provider.

AI output can be inaccurate, incomplete, biased, or overly confident. The app validates structure, not factual truth. Learners should verify important claims against trusted sources, especially for medical, legal, financial, safety-critical, or academic assessment use.

The project does not claim that generated lessons are original, authoritative, or suitable as a replacement for a teacher or primary source. The prompts request concise, topic-specific material and ask the model not to invent facts, but these instructions cannot guarantee correctness.

## Known limitations

- Generation depends on external AI provider availability, latency, quotas, and API keys.
- SSE reports application stages, but the current provider call is not token-by-token streamed. The final lesson arrives after the model request completes.
- The AI may return a valid-looking but factually incorrect lesson.
- Optional blocks depend on model output. A provider may return no blocks or malformed blocks that are safely discarded.
- Refinement requires the model to return a complete compatible lesson after the existing lesson is supplied as context. Very large lessons may exceed provider context or output limits.
- Retests are limited to three per topic and use prior question text as an exclusion hint; semantic duplication cannot be guaranteed.
- MongoDB availability is required for saving profile data, history, retests, refinement, and both guest and authenticated sessions.
- Guest workspaces are tied to browser local storage and are not transferable to a Google account automatically.
- Guest users do not have a verified identity or cross-device recovery path; login is the recommended mode for important study history.
- The active Learn-page cache uses browser local storage. Clearing site data removes it, and it is intentionally cleared on sign-out.
- Google OAuth must be configured for every development origin and deployment origin when Google login is enabled. Guest Mode does not require Google OAuth.
- The current frontend has no automated browser test suite or backend integration test suite.
- The app currently has a cinematic dark visual direction rather than a user-selectable light theme.
- Provider model names are constrained by the provider configuration in `backend/llm.py`.
- Google API calls use bearer credentials, while guest calls use the browser-scoped `X-Guest-ID` header. The application does not implement Google refresh-token management.
- The project does not include production deployment configuration, database migrations, rate limiting, background job processing, or centralized observability.

## Validation and development commands

Frontend build and type check:

```bash
cd frontend
npm run build
```

Backend syntax check:

```bash
cd backend
source .venv/bin/activate
python -m py_compile main.py models.py llm.py
```

Diff whitespace check:

```bash
git diff --check
```

There is currently no dedicated automated test command in `package.json` or `requirements.txt`. The build and syntax commands above are the repository's available baseline checks.

## Time spent

Approximate implementation and debugging time: **8-10 hours**.


- Full-stack project setup and environment troubleshooting.
- Responsive Learn, History, Profile, and Session UI work.
- Mobile navigation, logo, controls, focus states, and animation polish.
- AI lesson generation and schema validation.
- Streaming progress integration.
- Structured block modeling and rendering.
- Session persistence and reload restoration.
- Refinement and retest flows.
- Retest limits, CORS debugging, backend restarts, and validation passes.
- README and project documentation.

The estimate is approximate because development included iterative browser checks, model-response handling, local environment corrections, and responsive adjustments across multiple viewport sizes.

## License and project status

No explicit open-source license is currently included in the repository. Add a license before distributing the project publicly.

The project is a development-ready prototype: the primary learning workflow is implemented, persisted, and validated locally, while production concerns such as automated tests, rate limiting, deployment configuration, and stronger AI factuality safeguards remain future work.

