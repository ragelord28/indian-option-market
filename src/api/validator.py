import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
val_log_path = LOG_DIR / "validator.log"

val_handler = logging.FileHandler(val_log_path)
val_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
val_logger = logging.getLogger("validator")
val_logger.setLevel(logging.INFO)
if not val_logger.handlers:
    val_logger.addHandler(val_handler)

# Matches numbers with optional commas or dots (e.g. 450, 4,500, 10.5)
NUMBER_PATTERN = re.compile(r'\b\d[\d,\.]+\b')

def validate_provenance(llm_response: str, context: str) -> str:
    """
    Extracts numbers from the LLM output and validates they exist in the context payload.
    If a line contains ungrounded numbers, the line is redacted.
    """
    lines = llm_response.split('\n')
    validated_lines = []
    
    context_clean = context.replace(",", "")
    
    for line in lines:
        nums = NUMBER_PATTERN.findall(line)
        line_is_valid = True
        ungrounded_nums = []
        
        for num in nums:
            num_clean = num.replace(",", "")
            # Skip very short numbers (indices, counts like 1, 2, 3)
            if len(num_clean) <= 1:
                continue
                
            # If the number is not in raw context or comma-stripped context
            if num not in context and num_clean not in context_clean:
                # Ignore isolated year numbers if they look like current/future years, or single-digit decimals like '1.0'
                if not re.match(r'^20\d{2}$', num_clean) and not (len(num_clean) == 3 and num_clean.endswith(".0")):
                    line_is_valid = False
                    ungrounded_nums.append(num)
                    
        if line_is_valid:
            validated_lines.append(line)
        else:
            val_logger.info(f"Stripped ungrounded line. Nums: {ungrounded_nums} | Line: {line}")
            validated_lines.append(f"*[Redacted hallucinated line containing ungrounded numbers: {', '.join(ungrounded_nums)}]*")
            
    return '\n'.join(validated_lines)
