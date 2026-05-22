import os
import json
import uuid
from groq import Groq
from dotenv import load_dotenv
from models.schemas import MCQ, Choice
load_dotenv()
GROQ_API_KEY=os.getenv("GROQ_API_KEY")
MCQ_PER_SECTION=int(os.getenv("MCQ_PER_SECTION","5"))
MODEL="llama-3.3-70b-versatile"
client=Groq(api_key=GROQ_API_KEY)
def build_system_prompt()-> str:
        return """You are an expert  educational assessment designer.
    Your job is to generate Multiple Choice Questions (MCQs) from provided document sections.

    You must ALWAYS respond with ONLY a valid JSON array. No explanation, no markdown, no backticks.
    Just a raw JSON array like this:
    [
        {
        "question_text":"what is the mass ceiling for Inertial Suspension?",
        "choices":[
            {"label": "A", "text":"180 kg"},
            {"label": "B", "text":"240 kg"},
            {"label": "C", "text":"380 kg"},
            {"label": "D", "text":"120 kg"}    
        ],
        "correct_answer": "B",
        "explanation":"The controlled mass ceiling under standard operational conditions is 240 kg, established through CBMP testing",
        "topic_tag":"inertial_suspension"    
        }
    ]
    Rules you must follow:
    1. Always generate exactly the number of questions requested.
    2. Always include exactly 4 choices labeled A, B, C, D.
    3. The correct_answer must be one of: A, B, C, D.
    4. The explanation must reference specific facts from the provided text,
    5. The topic_tag must be a short snake_case label e.g. "powers", "equipment","tactics".
    6. Never include markdown, backticks, or any text outside the JSON array.
    7. Base all questions strictly on the provided document text."""
def build_user_prompt(
                section_id: int,
                section_text: str,
                n_questions: int,
                weak_topics: list[dict]=None,
                mastered_topics: list[str]=None,
                is_returning: bool=False
)-> str:
    prompt= f"""Generate exactly {n_questions} MCQ(s) based on Section {section_id} of the document below.
--- DOCUMENT SECTION {section_id} ---
{section_text[:4000]}
--- END OF SECTION ---
"""
    if is_returning and weak_topics:
            weak_list="\n".join([
                    f"- {t['topic_tag']} (answered incorrectly {t['wrong_count']} time(s))"
                    for t in weak_topics[:5]
                
            ])
            prompt+= f"""
    IMPORTANT - ADAPTIVE CONTEXT:
    This user has studied this section before. Focus your questions on these weak areas where the user has struggle in previous session:
    {weak_list}
    """
    if is_returning and mastered_topics:
            mastered_list=", ".join(mastered_topics[:5])
            prompt+= f"""AVOID generating on these already-mastered topics: {mastered_list}"""
    prompt += f"\nRespond with ONLY a JSON array of exactly {n_questions} MCQ objects."
    return prompt

def parse_llm_response(response_text: str, section_id: int)-> list[MCQ]:
    start=response_text.find("[")
    end=response_text.rfind("]")+1
    if start == -1 or end ==0:
            raise ValueError(
                f"LLM did not return valid JSON. Response was : \n{response_text[:500]}"
            )
    json_str=response_text[start:end]
    try:
           raw_questions=json.loads(json_str)
    except json.JSONDecodeError as e:
           raise ValueError(f"Failed to parse LLM JSON response: {e}\nRaw:{json_str[:500]}")
    mcqs=[]
    for i, raw in enumerate(raw_questions):
           short_id=str(uuid.uuid4()).replace("-","")[:6]
           question_id=f"q_{section_id}_{i+1:03d}_{short_id}"
           choices=[
                  Choice(label=c["label"],text=c["text"])
                  for c in raw["choices"]
           ]

           mcq=MCQ(
                  question_id=question_id,
                  section_id=section_id,
                  question_text=raw["question_text"],
                  choices=choices,
                  correct_answer=raw["correct_answer"],
                  explanation=raw["explanation"],
                  topic_tag=raw.get("topic_tag","general")
           )
           mcqs.append(mcq)
    return mcqs

def generate_mcqs(
              section_id: int,
              section_text: str,
              weak_topics: list[dict]=None,
              mastered_topics: list[str]=None,
              is_returning: bool=False
)-> list[MCQ]:
       system_prompt=build_system_prompt()
       user_prompt= build_user_prompt(
              section_id=section_id,
              section_text=section_text,
              n_questions=MCQ_PER_SECTION,
              weak_topics=weak_topics,
              mastered_topics=mastered_topics,
              is_returning=is_returning
       )
       response=client.chat.completions.create(
              model=MODEL,
              messages=[
                     {"role":"system", "content":system_prompt},
                     {"role":"user","content":user_prompt}
              ],
              temperature=0.7,
              max_tokens=2000,
       )
       response_text=response.choices[0].message.content
       return parse_llm_response(response_text=response_text, section_id=section_id)
            
    