import os
from core.kb import(
    get_sessions_for_sections,
    get_weak_topics,
    get_mastered_topics
)
from dotenv import load_dotenv
load_dotenv()
def analyze_history(section_ids: list[int])-> dict:
    prior_sessions=get_sessions_for_sections(section_ids=section_ids)
    if not prior_sessions:
        return{
            "is_returning": False,
            "weak_topics": [],
            "mastered_topics": [],
            "prior_session_count":0
        }
    weak_topics=get_weak_topics(section_ids=section_ids)
    mastered_topics=get_mastered_topics(section_ids=section_ids)
    # Fix 5: strip topics still marked weak out of the mastered list so the
    # LLM never receives contradictory "focus on this" + "avoid this" signals
    weak_tag_set={t["topic_tag"] for t in weak_topics}
    clean_mastered=[t for t in mastered_topics if t not in weak_tag_set]
    return{
        "is_returning":True,
        "weak_topics": weak_topics,
        "mastered_topics": clean_mastered,
        "prior_session_count":len(prior_sessions)
    }
def simulate_answers(mcqs:list)->list[dict]:
    import random
    random.seed(42)
    simulated=[]
    for i, mcq in enumerate(mcqs):
        if random.random()<0.65:
            selected=mcq.correct_answer
        else:
            wrong_options=[
                c.label for c in mcq.choices
                if c.label!= mcq.correct_answer
            ]
            # Fix 2: actually assign selected from wrong_options
            selected=random.choice(wrong_options)
        simulated.append({
            "question_id":mcq.question_id,
            "selected":selected
        })
    # Fix 1: return is now outside the loop
    return simulated
def build_adaptive_summary(section_ids:list[int])->str:
    context=analyze_history(section_ids=section_ids)
    if not context["is_returning"]:
        return "Cold start - No prior history found for these sections. Generating questions"
    lines=[]
    # Fix 4: added space between the two sentences
    lines.append(
        f"Returning user detected. "
        f"{context['prior_session_count']} prior session(s) found for sections {section_ids}."
    )
    # Fix 5: exclude topics still marked weak from the mastered list
    weak_tag_set={t["topic_tag"] for t in context["weak_topics"]}
    clean_mastered=[t for t in context["mastered_topics"] if t not in weak_tag_set]

    if context["weak_topics"]:
        weak_str=", ".join([
            f"{t['topic_tag']} ({t['wrong_count']} wrong)"
            for t in context["weak_topics"][:5]
        ])
        # Fix 3: actually append weak_str to lines
        lines.append(f"Weak areas to focus on: {weak_str}")
    else:
        lines.append("No weak areas identified yet.")
    if clean_mastered:
        mastered_str=", ".join(clean_mastered[:5])
        lines.append(f"Already mastered (will avoid repeating): {mastered_str}")

    return "\n".join(lines)