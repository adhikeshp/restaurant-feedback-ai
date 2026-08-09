"""All AI access stays server-side. The response is schema-validated before saving."""
import json, os, re
import httpx
from pydantic import BaseModel, Field
from typing import Literal

Category = Literal["FOOD CONTAMINATION", "FOOD QUALITY", "SERVER COMPLAINTS", "SURROUNDING AMBIENCE", "OTHERS"]
Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]

class Analysis(BaseModel):
    category: Category
    severity: Severity
    summary: str = Field(max_length=500)
    key_issue: str = Field(max_length=300)
    recommended_action: str = Field(max_length=500)
    priority_score: int = Field(ge=0, le=100)

SAFETY = re.compile(r"\b(glass|chemical|metal|plastic|stone|foreign object|shard|contaminat|poison|hair in (my |the )?food)\b", re.I)

def safety_override(text: str, value: Analysis) -> Analysis:
    if SAFETY.search(text):
        value.category = "FOOD CONTAMINATION"
        value.severity = "CRITICAL"
        value.priority_score = max(value.priority_score, 95)
        value.key_issue = "Potential food-safety contamination"
        value.recommended_action = "Immediately preserve the item, alert the manager, and inspect the food preparation process."
    return value

def local_analysis(text: str) -> Analysis:
    t = text.lower()
    if SAFETY.search(text):
        return Analysis(category="FOOD CONTAMINATION", severity="CRITICAL", summary="Customer reported a potential food-safety issue.", key_issue="Potential food-safety contamination", recommended_action="Immediately preserve the item, alert the manager, and inspect the food preparation process.", priority_score=98)
    if any(w in t for w in ["spoiled", "undercooked", "raw chicken", "sick"]):
        return Analysis(category="FOOD QUALITY", severity="HIGH", summary="Customer reported a significant food quality concern.", key_issue="Food quality concern", recommended_action="Review the affected dish and kitchen quality controls.", priority_score=82)
    if any(w in t for w in ["rude", "ignored", "server", "waiter", "waitress", "slow service"]):
        return Analysis(category="SERVER COMPLAINTS", severity="MEDIUM", summary="Customer reported a service experience issue.", key_issue="Service experience", recommended_action="Review the shift with the service lead and coach the team.", priority_score=59)
    if any(w in t for w in ["noise", "lighting", "chair", "parking", "clean", "ambience"]):
        return Analysis(category="SURROUNDING AMBIENCE", severity="MEDIUM", summary="Customer reported an environment concern.", key_issue="Dining environment", recommended_action="Review the condition during the next floor walk-through.", priority_score=52)
    return Analysis(category="OTHERS", severity="LOW", summary="Customer shared general feedback.", key_issue="General feedback", recommended_action="Log the feedback and review it in the next team meeting.", priority_score=25)

async def analyze_feedback(text: str) -> Analysis:
    key, model = os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")
    if not key or not model:
        return local_analysis(text)
    prompt = """Analyze this restaurant feedback. Return STRICT JSON only with category, severity, summary, key_issue, recommended_action, priority_score. Categories: FOOD CONTAMINATION, FOOD QUALITY, SERVER COMPLAINTS, SURROUNDING AMBIENCE, OTHERS. Severities: CRITICAL, HIGH, MEDIUM, LOW. Do not invent facts. priority_score 0-100. Feedback: """ + text
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{os.getenv('LLM_API_BASE','https://api.openai.com/v1').rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={"model": model, "messages": [{"role":"user","content":prompt}], "response_format":{"type":"json_object"}, "temperature":0})
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    return safety_override(text, Analysis.model_validate(json.loads(content)))
