from fastapi import APIRouter, HTTPException
from models.schemas import PrepRequest, SessionResult
from core.pdf_parser import get_sections, list_all_sections
from core.kb import(
    initialize_db,
    get_kb_snapshot,
    get_sessions_for_sections,
    save_session_with_mcqs,
    generate_session_id
)
from core.llm import generate_mcqs
from core.adaptive import (
    analyze_history,
    simulate_answers,
    build_adaptive_summary
)
from datetime import datetime
import json
import os
from models.schemas import AnswerResult
router=APIRouter()
@router.get("/sections")
def list_sections():
    try:
        previews=list_all_sections()
        return  {"sections":previews}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500,detail=str(e))
@router.post("/prep")
def run_prep_session(request:PrepRequest):
    initialize_db()
    if not request.section_ids:
        raise HTTPException(
            status_code=400,
            detail="section_ids can't be empty. Provide at least one section ID"
        )
    for sid in request.section_ids:
        if sid<1 or sid > 10:
            raise HTTPException(
                status_code=400,
                detail=f"Section {sid} is invalid. Valid sections are 1 through 10"

             )
    try:
        adaptive_context=analyze_history(request.section_ids)
        adaptive_summary=build_adaptive_summary(request.section_ids)
        sections=get_sections(request.section_ids)
        all_mcqs=[]
        for section_id, section_text in sections.items():
            mcqs=generate_mcqs(
                section_id=section_id,
                section_text=section_text,
                weak_topics=adaptive_context["weak_topics"],
                mastered_topics=adaptive_context["mastered_topics"],
                is_returning=adaptive_context["is_returning"]
            )
            all_mcqs.extend(mcqs)
        if request.simulate:
            raw_answers=simulate_answers(all_mcqs)
        else:
            return{
                "session_id":generate_session_id(),
                "adaptive_summary":adaptive_summary,
                "questions":[
                    {
                        "question_id": mcq.question_id,
                        "session_id": mcq.session_id,
                        "question_text": mcq.question_text,
                        "choices":[
                            {"label":c.label, "text": c.text}
                            for c in mcq.choices
                        ]
                    }
                    for mcq in all_mcqs
                ],
                "message":"Submit your answers to POST /answer"
            }
        mcq_lookup={mcq.question_id: mcq for mcq in all_mcqs}
        results=[]
        score=0
        for answer in raw_answers:
            mcq=mcq_lookup[answer["question_id"]]
            is_correct=answer["selected"]==mcq.correct_answer
            if is_correct:
                score+=1
            result=AnswerResult(
                question_id=mcq.question_id,
                question_text=mcq.question_text,
                selected=answer["selected"],
                correct_answer=mcq.correct_answer,
                is_correct=is_correct,
                explanation=mcq.explanation
            )
            results.append(result)
        session_id=generate_session_id()
        session_result=SessionResult(
            session_id=session_id,
            section_ids=request.section_ids,
            timestamp=datetime.now().isoformat(),
            score=score,
            total=len(all_mcqs),
            results=results
        )
        save_session_with_mcqs(
            session_result=session_result,
            mcqs=all_mcqs,
            simulated=request.simulate
        )
        response={
            "session_id":session_id,
            "adaptive_summary":adaptive_summary,
            "score": score,
            "total": len(all_mcqs),
            "percentage": round((score/len(all_mcqs))*100,1),
            "results":[
                {
                    "question_id":r.question_id,
                    "question_text":r.question_text,
                    "selected":r.selected,
                    "correct_answer":r.correct_answer,
                    "is_correct":r.is_correct,
                    "explanation": r.explanation if not r.is_correct else None
                }
                for r in results
            ]
        }
        return response
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422,detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/kb/snapshot")
def kb_snapshot():
    """
    GET /kb/snapshot
    Returns a snapshot of the 5 most recent sessions in the KB.
    This is required by the assessment spec — we call this after
    each scenario B iteration to verify the KB is storing data correctly.

    Returns a dict with snapshot_at timestamp and list of sessions
    each with their question-level results.
    """

    try:
        # initialize DB in case it hasn't been set up yet
        initialize_db()

        # get the snapshot from the KB
        snapshot = get_kb_snapshot()

        return snapshot

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{section_id}")
def get_section_history(section_id: int):
    """
    GET /history/{section_id}
    Returns all prior prep sessions for a given section.
    Useful for the user to see their history for a specific section.

    Example: GET /history/8 returns all sessions where section 8 was studied.
    """

    try:
        initialize_db()

        # get all sessions that involved this section
        sessions = get_sessions_for_sections([section_id])

        return {
            "section_id": section_id,
            "prior_sessions": len(sessions),
            "sessions": sessions
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def save_scenario_output(
    session_result: SessionResult,
    mcqs: list,
    iteration: int,
    output_dir: str
):
    """
    Saves the required scenario B output files for a given iteration.
    The assessment requires us to save two files per iteration:
    1. questions_iter{N}.json — the questions that were generated
    2. kb_snapshot_iter{N}.json — the KB state after this iteration

    This is called by main.py after each scenario B iteration completes.

    Parameters:
        session_result : the completed session result
        mcqs           : the list of MCQ objects that were generated
        iteration      : which iteration number (1, 2, or 3)
        output_dir     : path to the output folder for this iteration
    """

    # create the output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # --- file 1: questions_iter{N}.json ---
    # save the questions that were generated in this iteration
    questions_output = {
        "iteration": iteration,
        "session_id": session_result.session_id,
        "section_ids": session_result.section_ids,
        "timestamp": session_result.timestamp,
        "adaptive_summary": build_adaptive_summary(session_result.section_ids),
        "questions": [
            {
                "question_id": mcq.question_id,
                "section_id": mcq.section_id,
                "topic_tag": mcq.topic_tag,
                "question_text": mcq.question_text,
                "choices": [
                    {"label": c.label, "text": c.text}
                    for c in mcq.choices
                ],
                "correct_answer": mcq.correct_answer,
                "explanation": mcq.explanation
            }
            for mcq in mcqs
        ],
        "results": [
            {
                "question_id": r.question_id,
                "selected": r.selected,
                "correct_answer": r.correct_answer,
                "is_correct": r.is_correct
            }
            for r in session_result.results
        ],
        "score": session_result.score,
        "total": session_result.total,
        "percentage": round((session_result.score / session_result.total) * 100, 1)
    }

    # write questions file to disk as formatted JSON
    questions_path = os.path.join(output_dir, f"questions_iter{iteration}.json")
    with open(questions_path, "w") as f:
        # indent=2 makes the JSON human-readable
        json.dump(questions_output, f, indent=2)

    # --- file 2: kb_snapshot_iter{N}.json ---
    # save the current state of the KB after this iteration
    snapshot = get_kb_snapshot()
    snapshot_path = os.path.join(output_dir, f"kb_snapshot_iter{iteration}.json")
    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f, indent=2)

    # return the paths so main.py can print them to the terminal
    return {
        "questions_file": questions_path,
        "snapshot_file": snapshot_path
    }