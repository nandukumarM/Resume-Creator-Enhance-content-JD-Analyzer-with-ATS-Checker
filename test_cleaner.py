import re

def sanitize_resume_data(raw_pdf_text):
    """
    Cleans raw resume text by removing ATS-negative sections
    and formatting it for JSON structuring.
    """
    cleaned_text = raw_pdf_text
    
    # 1. Nuke the "Personal Details" section (Anti-discrimination laws)
    # This regex looks for "PERSONAL DETAILS:" and removes everything until "DECLARATION:"
    cleaned_text = re.sub(r'PERSONAL DETAILS:.*?(?=DECLARATION:|$)', '', cleaned_text, flags=re.DOTALL | re.IGNORECASE)
    
    # 2. Nuke the "Declaration" section (Obsolete practice)
    cleaned_text = re.sub(r'DECLARATION:.*', '', cleaned_text, flags=re.DOTALL | re.IGNORECASE)
    
    # 3. Clean up whitespace
    cleaned_text = re.sub(r'\n\s*\n', '\n', cleaned_text)
    
    return cleaned_text.strip()

test_text = """
JOHN DOE
Software Engineer

EXPERIENCE
- Dev at Corp

PERSONAL DETAILS:
Age: 30
Marital Status: Single
Religion: Jedi

DECLARATION:
I hereby declare that the above info is true.
"""

cleaned = sanitize_resume_data(test_text)
print("--- ORIGINAL ---")
print(test_text)
print("--- CLEANED ---")
print(cleaned)

if "PERSONAL DETAILS" not in cleaned and "DECLARATION" not in cleaned:
    print("\nSUCCESS: Personal Details and Declaration removed.")
else:
    print("\nFAILURE: Sections not removed.")
