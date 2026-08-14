from backend.core.message.prompts.learning import WORKSPACE_PROMPT as LEARNING_PROMPT
from backend.core.message.prompts.research import WORKSPACE_PROMPT as RESEARCH_PROMPT
from backend.core.message.prompts.teaching import WORKSPACE_PROMPT as TEACHING_PROMPT

WORKSPACE_PROMPTS = {
    "learning.v1": LEARNING_PROMPT,
    "teaching.v1": TEACHING_PROMPT,
    "research.v1": RESEARCH_PROMPT,
}

