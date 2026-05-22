# sqlite3 is Python's built-in database library
# it lets us create and query a local SQLite database file
# we chose SQLite because it requires zero setup — just a file on disk
# perfect for a local system like this where we don't need a server
import sqlite3

# os gives us tools to interact with the operating system
# we use it to read the DB_PATH from environment variables
import os

# json is Python's built-in JSON library
# we use it to serialize (convert to string) and deserialize (parse)
# complex objects like lists of choices before storing them in SQLite
# SQLite can't store Python lists directly, so we convert to JSON strings
import json

# datetime gives us the current time for timestamping sessions
from datetime import datetime

# uuid generates unique IDs for sessions and questions
# we use it so every session and question has a globally unique identifier
# uuid4() generates a random UUID like "a3f2c1d4-..."
import uuid

# load_dotenv reads our .env file into the environment
# so we can access DB_PATH and other config values
from dotenv import load_dotenv

# our data models — we import SessionResult and AnswerResult
# so we can convert database rows back into proper Python objects
from models.schemas import SessionResult, AnswerResult

# load the .env file
load_dotenv()

# DB_PATH is where our SQLite database file will be created
# defaults to "prep.db" in the project root if not set in .env
DB_PATH = os.getenv("DB_PATH", "prep.db")


def get_connection() -> sqlite3.Connection:
    """
    Creates and returns a connection to the SQLite database.
    We call this at the start of every database operation.
    sqlite3.connect() creates the file if it doesn't exist yet.
    We set row_factory so rows come back as dictionaries
    instead of plain tuples — much easier to work with.
    """

    # connect to the database file
    # if prep.db doesn't exist, sqlite3 creates it automatically
    conn = sqlite3.connect(DB_PATH)

    # row_factory = sqlite3.Row makes each row behave like a dict
    # so we can do row["session_id"] instead of row[0]
    conn.row_factory = sqlite3.Row

    return conn


def initialize_db():
    """
    Creates all the database tables if they don't exist yet.
    This is called once at startup before anything else.
    We use CREATE TABLE IF NOT EXISTS so it's safe to call multiple times
    without accidentally wiping existing data.

    Our schema has three tables:
    1. sessions   — one row per prep session
    2. questions  — one row per MCQ question asked in a session
    3. answers    — one row per user answer to a question
    """

    # get a connection to the database
    conn = get_connection()

    # cursor is what we use to execute SQL commands
    cursor = conn.cursor()

    # --- TABLE 1: sessions ---
    # stores high-level info about each prep session
    # one row = one time the user ran a prep session
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id   TEXT PRIMARY KEY,  -- unique ID for this session
            section_ids  TEXT NOT NULL,     -- JSON string of section IDs e.g. "[5, 8]"
            timestamp    TEXT NOT NULL,     -- when this session happened
            score        INTEGER NOT NULL,  -- how many questions correct
            total        INTEGER NOT NULL,  -- total questions in session
            simulated    INTEGER NOT NULL   -- 1 if answers were simulated, 0 if real
        )
    """)

    # --- TABLE 2: questions ---
    # stores every MCQ that was generated and asked in a session
    # one row = one question
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            question_id   TEXT PRIMARY KEY, -- unique ID for this question
            session_id    TEXT NOT NULL,    -- which session this question belongs to
            section_id    INTEGER NOT NULL, -- which dossier section this covers
            question_text TEXT NOT NULL,    -- the actual question text
            choices       TEXT NOT NULL,    -- JSON string of choices list
            correct_answer TEXT NOT NULL,  -- "A", "B", "C", or "D"
            explanation   TEXT NOT NULL,   -- why the correct answer is right
            topic_tag     TEXT NOT NULL,   -- short topic label for adaptive logic
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """)

    # --- TABLE 3: answers ---
    # stores what the user answered for each question
    # one row = one user answer
    # this is the table the adaptive logic queries to find weak areas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT, -- auto-incrementing row ID
            question_id   TEXT NOT NULL,    -- which question was answered
            session_id    TEXT NOT NULL,    -- which session this answer belongs to
            user_answer   TEXT NOT NULL,    -- what the user selected: "A","B","C","D"
            is_correct    INTEGER NOT NULL, -- 1 if correct, 0 if wrong
            timestamp     TEXT NOT NULL,    -- when this answer was submitted
            FOREIGN KEY (question_id) REFERENCES questions(question_id),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """)

    # commit saves all our CREATE TABLE statements to disk
    conn.commit()

    # always close the connection when done to free resources
    conn.close()


def save_session(session_result: SessionResult, simulated: bool = False):
    """
    Saves a completed prep session to the database.
    This is called at the end of every prep session (step 5 of the prep flow).
    It saves the session, all its questions, and all the user's answers.

    We save in three steps:
    1. Insert into sessions table
    2. Insert each question into questions table
    3. Insert each answer into answers table
    """

    conn = get_connection()
    cursor = conn.cursor()

    # --- step 1: save the session record ---
    cursor.execute("""
        INSERT INTO sessions (session_id, section_ids, timestamp, score, total, simulated)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        session_result.session_id,
        # convert the list of section IDs to a JSON string for storage
        json.dumps(session_result.section_ids),
        session_result.timestamp,
        session_result.score,
        session_result.total,
        # convert bool to int because SQLite has no boolean type
        1 if simulated else 0
    ))

    # --- step 2 & 3: save questions and answers ---
    # session_result.results is a list of AnswerResult objects
    # each AnswerResult has everything we need for both tables
    for result in session_result.results:

        # we need to get the full question data from the result
        # the question_id links the answer back to the question
        cursor.execute("""
            INSERT OR IGNORE INTO questions
            (question_id, session_id, section_id, question_text, choices, correct_answer, explanation, topic_tag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.question_id,
            session_result.session_id,
            # extract section from question_id format "q_{section}_{num}"
            int(result.question_id.split("_")[1]),
            result.question_text,
            # choices are stored as JSON string — we'll add them via MCQ later
            "[]",
            result.correct_answer,
            result.explanation,
            # topic_tag stored separately — will be updated by llm.py flow
            "general"
        ))

        # save the user's answer for this question
        cursor.execute("""
            INSERT INTO answers (question_id, session_id, user_answer, is_correct, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (
            result.question_id,
            session_result.session_id,
            result.selected,
            # convert bool to int for SQLite
            1 if result.is_correct else 0,
            datetime.now().isoformat()
        ))

    # commit everything at once — if anything fails, nothing gets saved
    # this is called an atomic transaction
    conn.commit()
    conn.close()


def save_session_with_mcqs(session_result: SessionResult, mcqs: list, simulated: bool = False):
    """
    Enhanced version of save_session that also saves full MCQ data
    including choices and topic_tags from the original MCQ objects.
    This is what the main flow actually calls.
    """

    conn = get_connection()
    cursor = conn.cursor()

    # save the session record first
    cursor.execute("""
        INSERT INTO sessions (session_id, section_ids, timestamp, score, total, simulated)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        session_result.session_id,
        json.dumps(session_result.section_ids),
        session_result.timestamp,
        session_result.score,
        session_result.total,
        1 if simulated else 0
    ))

    # build a lookup dict from question_id to MCQ object
    # so we can quickly find the full MCQ data for each answer result
    mcq_lookup = {mcq.question_id: mcq for mcq in mcqs}

    # save each question and its answer
    for result in session_result.results:

        # get the full MCQ object for this question
        mcq = mcq_lookup.get(result.question_id)

        # convert choices list to JSON string for storage
        choices_json = json.dumps(
            [{"label": c.label, "text": c.text} for c in mcq.choices]
        ) if mcq else "[]"

        # get topic_tag from the MCQ object
        topic_tag = mcq.topic_tag if mcq else "general"

        # get section_id from the MCQ object
        section_id = mcq.section_id if mcq else int(result.question_id.split("_")[1])

        # insert the question record
        cursor.execute("""
            INSERT OR IGNORE INTO questions
            (question_id, session_id, section_id, question_text, choices, correct_answer, explanation, topic_tag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.question_id,
            session_result.session_id,
            section_id,
            result.question_text,
            choices_json,
            result.correct_answer,
            result.explanation,
            topic_tag
        ))

        # insert the answer record
        cursor.execute("""
            INSERT INTO answers (question_id, session_id, user_answer, is_correct, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (
            result.question_id,
            session_result.session_id,
            result.selected,
            1 if result.is_correct else 0,
            datetime.now().isoformat()
        ))

    conn.commit()
    conn.close()


def get_sessions_for_sections(section_ids: list[int]) -> list[dict]:
    """
    Retrieves all prior prep sessions that involved any of the given sections.
    This is step 1 of the prep flow — checking if there's any history.
    Called by adaptive.py to get context for returning runs.

    Example: get_sessions_for_sections([5, 8]) returns all sessions
    where section 5 or section 8 was studied.
    """

    conn = get_connection()
    cursor = conn.cursor()

    # we query all sessions and then filter in Python
    # because section_ids is stored as a JSON string in SQLite
    # it's easier to parse and check in Python than in SQL
    cursor.execute("""
        SELECT * FROM sessions ORDER BY timestamp DESC
    """)

    all_sessions = cursor.fetchall()
    conn.close()

    # filter sessions that overlap with the requested section IDs
    matching = []
    for row in all_sessions:
        # parse the JSON string back into a Python list
        stored_ids = json.loads(row["section_ids"])

        # check if any of the requested sections appear in this session
        if any(sid in stored_ids for sid in section_ids):
            matching.append(dict(row))

    return matching


def get_weak_topics(section_ids: list[int]) -> list[dict]:
    """
    Identifies topics where the user has consistently given wrong answers
    across multiple sessions for the given sections.

    This is the core of the adaptive logic — we find weak areas
    and pass them to the LLM so it generates targeted questions.

    Returns a list of dicts with topic_tag and wrong_count,
    sorted by wrong_count descending (worst topics first).
    """

    conn = get_connection()
    cursor = conn.cursor()

    # join questions and answers tables to get topic-level performance
    # we count how many times each topic_tag was answered incorrectly
    # filtering to only the sections we care about
    placeholders = ",".join("?" * len(section_ids))
    cursor.execute(f"""
        SELECT
            q.topic_tag,
            q.section_id,
            COUNT(*) as wrong_count
        FROM answers a
        JOIN questions q ON a.question_id = q.question_id
        WHERE a.is_correct = 0
        AND q.section_id IN ({placeholders})
        GROUP BY q.topic_tag, q.section_id
        ORDER BY wrong_count DESC
    """, tuple(section_ids))

    rows = cursor.fetchall()
    conn.close()

    # convert sqlite3.Row objects to plain dicts
    return [dict(row) for row in rows]


def get_mastered_topics(section_ids: list[int]) -> list[str]:
    """
    Returns topic tags where the user has answered correctly
    more than twice across sessions.
    The adaptive logic uses this to avoid repeating questions
    on topics the user has already mastered.
    """

    conn = get_connection()
    cursor = conn.cursor()

    placeholders = ",".join("?" * len(section_ids))
    cursor.execute(f"""
        SELECT
            q.topic_tag,
            COUNT(*) as correct_count
        FROM answers a
        JOIN questions q ON a.question_id = q.question_id
        WHERE a.is_correct = 1
        AND q.section_id IN ({placeholders})
        GROUP BY q.topic_tag
        HAVING correct_count >= 3
    """, tuple(section_ids))

    rows = cursor.fetchall()
    conn.close()

    # return just the topic tag strings
    return [row["topic_tag"] for row in rows]


def get_kb_snapshot() -> dict:
    """
    Returns a human-readable snapshot of the knowledge base.
    Shows the 5 most recent sessions with their question-level results.

    This is required by the assessment — we export this after each
    scenario B iteration so the reviewer can verify the KB is correct.
    """

    conn = get_connection()
    cursor = conn.cursor()

    # get the 5 most recent sessions
    cursor.execute("""
        SELECT * FROM sessions ORDER BY timestamp DESC LIMIT 5
    """)
    sessions = cursor.fetchall()

    snapshot = {
        # record when this snapshot was taken
        "snapshot_at": datetime.now().isoformat(),
        "sessions": []
    }

    for session in sessions:
        session_dict = dict(session)

        # parse section_ids back from JSON string
        session_dict["section_ids"] = json.loads(session_dict["section_ids"])

        # get all answers for this session with question details
        cursor.execute("""
            SELECT
                a.question_id,
                q.question_text,
                q.topic_tag,
                q.section_id,
                a.user_answer,
                q.correct_answer,
                a.is_correct
            FROM answers a
            JOIN questions q ON a.question_id = q.question_id
            WHERE a.session_id = ?
            ORDER BY a.id ASC
        """, (session_dict["session_id"],))

        answers = cursor.fetchall()

        # attach the question-level details to the session
        session_dict["questions"] = [dict(a) for a in answers]

        snapshot["sessions"].append(session_dict)

    conn.close()

    return snapshot


def generate_session_id() -> str:
    """
    Generates a unique session ID combining timestamp and UUID.
    Format: sess_YYYYMMDD_HHMMSS_<short_uuid>
    Example: sess_20260519_143022_a3f2c1
    Easy to read and guaranteed unique.
    """

    # get current timestamp formatted as YYYYMMDD_HHMMSS
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # get first 6 characters of a random UUID for uniqueness
    short_uuid = str(uuid.uuid4()).replace("-", "")[:6]

    return f"sess_{timestamp}_{short_uuid}"