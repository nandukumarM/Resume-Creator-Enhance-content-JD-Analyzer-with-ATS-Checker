"""
Smart ATS Checker - Advanced Resume Analysis System
A Flask-based web application that uses Google Gemini AI to analyze resumes
and provide ATS scoring, job matching, and improvement suggestions.
"""

from flask import Flask, render_template, request, jsonify, session, send_file, redirect, url_for
from werkzeug.utils import secure_filename
import os
import json
import uuid
from datetime import datetime
import fitz  # PyMuPDF
from groq import Groq
from dotenv import load_dotenv
import re
import io
import time
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from itertools import zip_longest
from xhtml2pdf import pisa
from functools import wraps
import werkzeug.security as ws

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ANALYSIS_FOLDER'] = 'analysis_data'
app.config['ALLOWED_EXTENSIONS'] = {'pdf'}

# Configure Groq AI
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
client = None

if GROQ_API_KEY:
    try:
        client = Groq(api_key=GROQ_API_KEY)
        print(f"Groq Client Initialized. Key ends with: ...{GROQ_API_KEY[-5:]}")
    except Exception as e:
        print(f"Failed to initialize Groq client: {e}")
else:
    print("Warning: GROQ_API_KEY not found in environment variables.")
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['ANALYSIS_FOLDER'], exist_ok=True)
os.makedirs('static', exist_ok=True)
os.makedirs('templates', exist_ok=True)

# Data Stores
USERS_FILE = os.path.join(app.config['ANALYSIS_FOLDER'], 'users.json')
HISTORY_FILE = os.path.join(app.config['ANALYSIS_FOLDER'], 'history.json')

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r') as f:
        try: return json.load(f)
        except: return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=4)

def add_history_entry(user_id, doc_type, filename, title="Untitled"):
    history = load_history()
    entry = {
        'id': str(uuid.uuid4()),
        'user_id': user_id,
        'doc_type': doc_type,
        'filename': filename,
        'title': title,
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    history.insert(0, entry) # Add to beginning
    save_history(history)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# In-memory storage for analysis results (use database in production)
analysis_storage = {}


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

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


def allowed_file(filename):
    """Check if uploaded file has allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def extract_text_from_pdf(pdf_path):
    """
    Extract text content from PDF file using PyMuPDF
    Returns: Extracted text as string
    """
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return "" # Return empty string instead of crashing, let validation handle it

def clean_json_response(text):
    """Clean and parse JSON response from AI"""
    try:
        # Find the first '{' and last '}'
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        
        if start_idx != -1 and end_idx != -1:
            json_str = text[start_idx:end_idx+1]
            return json.loads(json_str)
        
        # Fallback for standard markdown
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        
        return json.loads(text.strip())
    except Exception as e:
        print(f"JSON Parse Error. Raw text: {text}")
        # Try one more time with simple cleanup
        try:
             return json.loads(text.replace("```json", "").replace("```", "").strip())
        except:
             raise Exception(f"Failed to parse AI response: {str(e)}")


def analyze_with_groq(resume_text, job_description=None):
    """
    Analyze resume using Groq (Llama 3)
    Returns: Structured analysis results as dictionary
    """
    try:
        if not client:
            raise Exception("Groq client not initialized. Check API Key.")

        prompt = f"""
You are an expert ATS (Applicant Tracking System) analyzer and career coach. Analyze the following resume and provide a comprehensive evaluation.

RESUME TEXT:
{resume_text}

{"JOB DESCRIPTION: " + job_description if job_description else "No specific job description provided."}

Provide a detailed analysis in valid JSON format with the following structure:
{{
    "ats_score": <number between 0-100>,
    "candidate_summary": {{
        "name": "<extracted name or 'Not found'>",
        "email": "<extracted email or 'Not found'>",
        "phone": "<extracted phone or 'Not found'>",
        "experience_years": "<estimated years>",
        "current_role": "<current or most recent role>",
        "overview": "<2-3 sentence professional summary>"
    }},
    "resume_strength": {{
        "score": <number between 0-100>,
        "content_quality": "<assessment of content quality>",
        "formatting": "<assessment of formatting and structure>",
        "keyword_density": "<percentage or assessment>",
        "strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
        "weaknesses": ["<weakness 1>", "<weakness 2>", "<weakness 3>"]
    }},
    "job_match": {{
        "score": <number between 0-100>,
        "matching_skills": ["<skill 1>", "<skill 2>", "<skill 3>"],
        "missing_skills": ["<skill 1>", "<skill 2>", "<skill 3>"],
        "relevance_assessment": "<detailed assessment of how well resume matches job>"
    }},
    "skill_analysis": {{
        "technical_skills": ["<skill 1>", "<skill 2>", "<skill 3>"],
        "soft_skills": ["<skill 1>", "<skill 2>", "<skill 3>"],
        "certifications": ["<cert 1>", "<cert 2>"],
        "skill_gaps": ["<missing skill 1>", "<missing skill 2>"],
        "recommended_skills": ["<skill to add 1>", "<skill to add 2>"]
    }},
    "grammar_feedback": {{
        "score": <number between 0-100>,
        "issues_found": <number of issues>,
        "common_errors": ["<error 1>", "<error 2>"],
        "suggestions": ["<suggestion 1>", "<suggestion 2>"]
    }},
    "ai_suggestions": {{
        "immediate_improvements": ["<improvement 1>", "<improvement 2>", "<improvement 3>"],
        "section_improvements": {{
            "summary": "<how to improve summary section>",
            "experience": "<how to improve experience section>",
            "skills": "<how to improve skills section>",
            "education": "<how to improve education section>"
        }},
        "keyword_recommendations": ["<keyword 1>", "<keyword 2>", "<keyword 3>"],
        "formatting_tips": ["<tip 1>", "<tip 2>", "<tip 3>"]
    }},
    "enhanced_sections": {{
        "improved_summary": "<AI-generated improved professional summary>",
        "improved_experience": "<AI-generated improved experience bullet points>",
        "action_verbs": ["<verb 1>", "<verb 2>", "<verb 3>"]
    }},
    "comparison": {{
        "your_resume": {{
            "pros": ["<pro 1>", "<pro 2>"],
            "cons": ["<con 1>", "<con 2>"]
        }},
        "ideal_resume": {{
            "should_have": ["<element 1>", "<element 2>"],
            "best_practices": ["<practice 1>", "<practice 2>"]
        }}
    }}
}}

Provide only valid JSON, no additional text or explanation. 
IMPORTANT: Ensure valid JSON output.
"""

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=4096,
            top_p=1,
            stream=False,
            response_format={"type": "json_object"}
        )

        return clean_json_response(completion.choices[0].message.content)

    except Exception as e:
        raise Exception(f"Groq API analysis failed: {str(e)}")


def generate_enhanced_pdf(analysis_data, original_text):
    """Generate an AI-enhanced resume PDF"""
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        # Title
        title = Paragraph("<b>AI-Enhanced Resume: Upgrade your resume.</b>", styles['Title'])
        story.append(title)
        story.append(Spacer(1, 12))

        # Candidate Information
        try:
            if 'candidate_summary' in analysis_data:
                candidate = analysis_data['candidate_summary']
                if isinstance(candidate, dict):
                    name = str(candidate.get('name', 'N/A'))
                    email = str(candidate.get('email', 'N/A'))
                    phone = str(candidate.get('phone', 'N/A'))
                    
                    story.append(Paragraph(f"<b>Name:</b> {name}", styles['Normal']))
                    story.append(Paragraph(f"<b>Email:</b> {email}", styles['Normal']))
                    story.append(Paragraph(f"<b>Phone:</b> {phone}", styles['Normal']))
                    story.append(Spacer(1, 12))
        except Exception as e:
            print(f"Error adding candidate info: {e}")

        # Improved Professional Summary
        story.append(Paragraph("<b>Professional Summary</b>", styles['Heading2']))
        try:
            summary_added = False
            if 'enhanced_sections' in analysis_data:
                enhanced = analysis_data['enhanced_sections']
                if isinstance(enhanced, dict) and 'improved_summary' in enhanced:
                    summary_text = str(enhanced['improved_summary'])
                    if summary_text and summary_text != 'None':
                        story.append(Paragraph(summary_text, styles['BodyText']))
                        summary_added = True
            
            if not summary_added and 'candidate_summary' in analysis_data:
                candidate = analysis_data['candidate_summary']
                if isinstance(candidate, dict) and 'overview' in candidate:
                    summary_text = str(candidate['overview'])
                    if summary_text and summary_text != 'None':
                        story.append(Paragraph(summary_text, styles['BodyText']))
                        summary_added = True
            
            if not summary_added:
                story.append(Paragraph("Professional with demonstrated experience in the field.", styles['BodyText']))
        except Exception as e:
            print(f"Error adding summary: {e}")
            story.append(Paragraph("Professional with demonstrated experience in the field.", styles['BodyText']))
        
        story.append(Spacer(1, 12))

        # Key Skills
        story.append(Paragraph("<b>Key Skills</b>", styles['Heading2']))
        try:
            if 'skill_analysis' in analysis_data:
                skills = analysis_data['skill_analysis']
                
                if isinstance(skills, dict):
                    # Technical Skills
                    if 'technical_skills' in skills:
                        tech_skills_list = skills['technical_skills']
                        if isinstance(tech_skills_list, list) and tech_skills_list:
                            tech_skills = ', '.join([str(s) for s in tech_skills_list[:10]])
                            story.append(Paragraph(f"<b>Technical:</b> {tech_skills}", styles['Normal']))
                    
                    # Soft Skills
                    if 'soft_skills' in skills:
                        soft_skills_list = skills['soft_skills']
                        if isinstance(soft_skills_list, list) and soft_skills_list:
                            soft_skills = ', '.join([str(s) for s in soft_skills_list[:10]])
                            story.append(Paragraph(f"<b>Soft Skills:</b> {soft_skills}", styles['Normal']))
        except Exception as e:
            print(f"Error adding skills: {e}")
        
        story.append(Spacer(1, 12))

        # Enhanced Experience Section
        story.append(Paragraph("<b>Professional Experience</b>", styles['Heading2']))
        try:
            exp_added = False
            if 'enhanced_sections' in analysis_data:
                enhanced = analysis_data['enhanced_sections']
                if isinstance(enhanced, dict) and 'improved_experience' in enhanced:
                    exp_text = enhanced['improved_experience']
                    if isinstance(exp_text, str) and exp_text and exp_text != 'None':
                        # Split by newlines and create paragraphs
                        exp_lines = exp_text.split('\n')
                        for line in exp_lines[:20]:  # Limit to 20 lines
                            if line.strip():
                                story.append(Paragraph(line.strip(), styles['BodyText']))
                        exp_added = True
            
            if not exp_added and original_text:
                # Use original text (first 1500 chars)
                original_preview = str(original_text)[:1500] if len(str(original_text)) > 1500 else str(original_text)
                # Clean the text
                original_preview = original_preview.replace('\n\n', '<br/><br/>').replace('\n', ' ')
                story.append(Paragraph(original_preview, styles['BodyText']))
        except Exception as e:
            print(f"Error adding experience: {e}")
            story.append(Paragraph("Experienced professional with a strong background.", styles['BodyText']))
        
        story.append(Spacer(1, 12))

        # AI Recommendations
        story.append(Paragraph("<b>AI Recommendations</b>", styles['Heading2']))
        try:
            if 'ai_suggestions' in analysis_data:
                suggestions = analysis_data['ai_suggestions']
                if isinstance(suggestions, dict) and 'immediate_improvements' in suggestions:
                    improvements = suggestions['immediate_improvements']
                    if isinstance(improvements, list):
                        for i, improvement in enumerate(improvements[:5], 1):
                            improvement_text = str(improvement)
                            story.append(Paragraph(f"{i}. {improvement_text}", styles['Normal']))
        except Exception as e:
            print(f"Error adding recommendations: {e}")
        
        story.append(Spacer(1, 24))

        # Footer
        story.append(Paragraph("<i>Generated by ATS Checker - AI-Powered Resume Analyzer</i>", styles['Normal']))

        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer

    except Exception as e:
        print(f"PDF generation error details: {str(e)}")
        import traceback
        traceback.print_exc()
        raise Exception(f"PDF generation failed: {str(e)}")


def generate_custom_resume(resume_text, target_job_description):
    """
    Generate a tailored resume using Groq (Llama 3)
    """
    try:
        if not client:
             raise Exception("Groq client not initialized")

        print("[DEBUG] Calling Groq API for resume generation...")
        prompt = f"""
        You are an expert professional resume writer specialized in ATS (Applicant Tracking System) optimization. I will provide a candidate's existing resume content and a target Job Description.
        Your task is to REWRITE and TAILOR the resume to specifically target this job description.

        CORE INSTRUCTIONS:
        1. ANALYZE the Job Description to identify key skills, keywords, and requirements.
        2. REWRITE the candidate's professional summary to align with these requirements, highlighting their most relevant experience.
        3. TAILOR the bullet points in the Experience section. Use strong action verbs and emphasize results that matter for the target role.
        4. REORDER skills to prioritize those mentioned in the JD.

        RULES:
        - Use ONLY facts from the existing resume. Do NOT invent experiences or skills not present in the source text.
        - You MAY rephrase, summarize, or expand on existing points to better match the JD's language.
        - Use STANDARD SECTION HEADINGS: "Professional Summary", "Experience", "Education", "Skills", "Projects".
        - NO tables, NO columns, NO graphics. Plain text structure is essential.

        EXISTING RESUME:
        {resume_text}

        TARGET JOB DESCRIPTION:
        {target_job_description}

        Output a comprehensive JSON object for the new resume with this structure:
        {{
            "personal_info": {{
                "name": "...",
                "contact_info": "..."
            }},
            "summary": "...",
            "skills": {{
                "technical": ["..."],
                "soft": ["..."]
            }},
            "experience": [
                {{
                    "title": "...",
                    "company": "...",
                    "dates": "...",
                    "bullets": ["...", "..."]
                }}
            ],
            "education": [
                {{
                    "degree": "...",
                    "school": "...",
                    "dates": "..."
                }}
            ],
            "projects": [
                {{
                    "name": "...",
                    "description": "...",
                    "technologies": "..."
                }}
            ]
        }}
        Provide only valid JSON.
        """
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a resume expert that outputs valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=4096,
            stream=False,
            response_format={"type": "json_object"}
        )
        print("[DEBUG] Groq API response received.")
        return clean_json_response(completion.choices[0].message.content)

    except Exception as e:
        print(f"Resume Gen Error: {e}")
        raise Exception(f"Resume generation failed: {str(e)}")

def analyze_job_description_with_ai(job_description):
    """
    Analyze job description using Groq
    """
    try:
        if not client: raise Exception("Groq client not initialized")
        
        prompt = f"""
You are an expert HR Specialist and Technical Recruiter. Analyze the following Job Description to extract structured information.

JOB DESCRIPTION:
{job_description}

INSTRUCTIONS:
1. Extract explicit Technical Skills. Be uniform and comprehensive. Extract as many relevant tools, languages, frameworks, and concepts as possible (aim for 10+).
2. Extract OR INFER Soft Skills. If not explicitly stated, you MUST infer at least 5-8 relevant soft skills based on the role responsibilities (e.g., "Communication", "Problem Solving", "Leadership"). Do not leave soft skills empty.
3. Extract at least 15-20 Critical Keywords from the JD. These should include technologies, methodologies, certifications, and industry terms.
4. Summarize the Core Responsibilities. Explain what the role entails in 5-7 clear bullet points. If responsibilities are not explicitly listed, infer them from the summary and title.

Provide a comprehensive analysis in valid JSON format with the following structure:
{{
    "job_title": "<extracted title or 'Unknown'>",
    "summary": "<brief 2-sentence summary of the role>",
    "skills": {{
        "technical": ["<skill 1>", "<skill 2>", "..."],
        "soft": ["<skill 1>", "<skill 2>", "..."]
    }},
    "qualifications": ["<qualification 1>", "<qualification 2>", "..."],
    "responsibilities": ["<responsibility 1>", "<responsibility 2>", "..."],
    "keywords": [
        {{"keyword": "<keyword 1>", "importance": "High"}},
        {{"keyword": "<keyword 2>", "importance": "Medium"}}
    ],
    "culture_fit_clues": ["<clue 1>", "<clue 2>"]
}}
Provide only valid JSON.
"""
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=2048,
            response_format={"type": "json_object"}
        )
        
        # Parse response
        raw_response = clean_json_response(completion.choices[0].message.content)
        
        # Ensure default structure
        default_structure = {
            "job_title": "Job Title Not Found",
            "summary": "No summary available.",
            "skills": {
                "technical": [],
                "soft": []
            },
            "qualifications": [],
            "responsibilities": [],
            "keywords": [],
            "culture_fit_clues": []
        }
        
        # Merge default with response (shallow merge for top level)
        final_response = {**default_structure, **raw_response}
        
        # Ensure deep keys exist if 'skills' was overwritten but incomplete
        if 'skills' not in final_response or not isinstance(final_response['skills'], dict):
             final_response['skills'] = default_structure['skills']
        else:
             if 'technical' not in final_response['skills']:
                 final_response['skills']['technical'] = []
             if 'soft' not in final_response['skills']:
                 final_response['skills']['soft'] = []
                 
        return final_response

    except Exception as e:
        print(f"JD Analysis Error: {e}")
        raise Exception(f"JD Analysis failed: {str(e)}")

def rewrite_resume_section(text, improvement_type="Professional"):
    """
    Rewrite resume text based on selected style using Groq
    """
    try:
        if not client: raise Exception("Groq client not initialized")

        prompt = f"""
You are an expert professional resume editor. Rewrite the following text to make it more impactful.

TEXT TO IMPROVE:
{text}

IMPROVEMENT STYLE: {improvement_type}

Specific Instructions for {improvement_type}:
- Professional: Use strong action verbs, formal tone, and precise language.
- Creative: Use engaging language, slightly more vivid descriptors, but keep it professional.
- ATS-Friendly: Focus on standard keywords, simple formatting, and clarity.
- Concise: Shorten sentences, remove fluff, get straight to the point.
- Action-Oriented: Start every bullet/sentence with a powerful action verb.

Provide the improved text. Do not include explanations, just the rewritten content.
"""
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a helpful editor."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1024
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        raise Exception(f"Content rewrite failed: {str(e)}")

def generate_two_column_pdf(resume_data, accent_color=colors.teal):
    """Generate a Two-Column Modern PDF Resume with Pagination Fix and Full Bleed"""
    try:
        buffer = io.BytesIO()
        # Full Bleed: Set all margins to 0
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=0, leftMargin=0, topMargin=0, bottomMargin=0)
        styles = getSampleStyleSheet()
        
        # Dimensions
        page_width, page_height = letter
        sidebar_width = 200  # Wider sidebar
        main_width = page_width - sidebar_width
        
        # Custom Styles
        # Increase padding in styles since we lost page margins
        style_left_header = ParagraphStyle('LeftHeader', parent=styles['Heading3'], textColor=colors.white, spaceAfter=8)
        style_left_text = ParagraphStyle('LeftText', parent=styles['Normal'], textColor=colors.white, fontSize=9, leading=12)
        style_right_header = ParagraphStyle('RightHeader', parent=styles['Heading3'], textColor=accent_color, spaceAfter=8, borderPadding=0)
        style_right_text = ParagraphStyle('RightText', parent=styles['BodyText'], fontSize=10, leading=14)
        style_name = ParagraphStyle('Name', parent=styles['Title'], textColor=accent_color, alignment=0, spaceAfter=10, fontSize=24)
        
        # --- LEFT COLUMN CHUNKS ---
        left_chunks = []
        
        # Add a top spacer
        left_chunks.append([Spacer(1, 20)]) 

        # 0. Profile Photo
        if 'personal_info' in resume_data and resume_data['personal_info'].get('photo_path'):
            try:
                photo_path = resume_data['personal_info']['photo_path']
                if os.path.exists(photo_path):
                    # Create an Image with fixed width, maintaining aspect ratio usually handled by providing only one dim or scaling
                    img = Image(photo_path, width=120, height=120) 
                    # ReportLab Image width/height are the box size. We might need to scale image.
                    # For simplicity, let's force a square or appropriate size.
                    # Aspect ratio preservation is better done by calculating:
                    # img = Image(photo_path)
                    # img.drawHeight = 120 * img.drawHeight / img.drawWidth
                    # img.drawWidth = 120
                    
                    # Or just use the arguments to limit size
                    img.hAlign = 'CENTER'
                    left_chunks.append([img, Spacer(1, 15)])
            except Exception as e:
                print(f"Error adding photo: {e}")
        
        # 1. Contact Info
        if 'personal_info' in resume_data:
            info = resume_data['personal_info']
            if 'contact_info' in info:
                chunk = []
                chunk.append(Paragraph("<b>CONTACT</b>", style_left_header))
                contacts = info['contact_info'].replace(' | ', '\n').replace(', ', '\n').replace(' • ', '\n').split('\n')
                for contact in contacts:
                    chunk.append(Paragraph(contact, style_left_text))
                chunk.append(Spacer(1, 15))
                left_chunks.append(chunk)

        # 2. Skills
        if 'skills' in resume_data:
            chunk = []
            chunk.append(Paragraph("<b>SKILLS</b>", style_left_header))
            skills = resume_data['skills']
            if isinstance(skills, dict):
                if 'technical' in skills:
                    chunk.append(Paragraph("<b>Technical:</b>", style_left_text))
                    for skill in skills['technical']:
                        chunk.append(Paragraph(f"• {skill}", style_left_text))
                    chunk.append(Spacer(1, 5))
                if 'soft' in skills:
                    chunk.append(Paragraph("<b>Soft:</b>", style_left_text))
                    for skill in skills['soft']:
                         chunk.append(Paragraph(f"• {skill}", style_left_text))
            elif isinstance(skills, list):
                for skill in skills:
                    chunk.append(Paragraph(f"• {skill}", style_left_text))
            chunk.append(Spacer(1, 15))
            left_chunks.append(chunk)

        # 3. Education
        if 'education' in resume_data:
            chunk = []
            chunk.append(Paragraph("<b>EDUCATION</b>", style_left_header))
            for edu in resume_data['education']:
                school = edu.get('school', '')
                degree = edu.get('degree', '')
                dates = edu.get('dates', '')
                score = edu.get('score', '')
                
                chunk.append(Paragraph(f"<b>{school}</b>", style_left_text))
                chunk.append(Paragraph(degree, style_left_text))
                chunk.append(Paragraph(dates, style_left_text))
                if score:
                    chunk.append(Paragraph(f"Score: {score}", style_left_text))
                chunk.append(Spacer(1, 8))
            left_chunks.append(chunk)

        # 4. Certifications
        if 'certifications' in resume_data and resume_data['certifications']:
            chunk = []
            chunk.append(Paragraph("<b>CERTIFICATIONS</b>", style_left_header))
            for cert in resume_data['certifications']:
                name = cert.get('name', '')
                auth = cert.get('authority', '')
                year = cert.get('year', '')
                chunk.append(Paragraph(f"<b>{name}</b>", style_left_text))
                chunk.append(Paragraph(f"{auth} ({year})", style_left_text))
                chunk.append(Spacer(1, 5))
            left_chunks.append(chunk)

        # 5. Languages
        if 'languages' in resume_data and resume_data['languages']:
            chunk = []
            chunk.append(Paragraph("<b>LANGUAGES</b>", style_left_header))
            for lang in resume_data['languages']:
                chunk.append(Paragraph(f"• {lang}", style_left_text))
            chunk.append(Spacer(1, 15))
            left_chunks.append(chunk)
        
        # --- RIGHT COLUMN CHUNKS ---
        right_chunks = []
        
        # Add a top spacer for margin simulation
        right_chunks.append([Spacer(1, 30)])
        
        # 1. Name
        if 'personal_info' in resume_data:
             name = resume_data['personal_info'].get('name', 'Candidate')
             right_chunks.append([Paragraph(name.upper(), style_name)])
        
        # 2. Career Objective
        if 'career_objective' in resume_data and resume_data['career_objective']:
            chunk = []
            chunk.append(Paragraph("CAREER OBJECTIVE", style_right_header))
            chunk.append(Paragraph(resume_data['career_objective'], style_right_text))
            chunk.append(Spacer(1, 12))
            right_chunks.append(chunk)

        # 3. Summary
        if 'summary' in resume_data and resume_data['summary']:
            chunk = []
            chunk.append(Paragraph("PROFESSIONAL SUMMARY", style_right_header))
            chunk.append(Paragraph(resume_data['summary'], style_right_text))
            chunk.append(Spacer(1, 12))
            right_chunks.append(chunk)
            
        # 4. Experience (One chunk per job to allow splitting)
        if 'experience' in resume_data:
            # Header
            right_chunks.append([Paragraph("EXPERIENCE", style_right_header)])
            
            for job in resume_data['experience']:
                chunk = []
                title = job.get('title', '')
                company = job.get('company', '')
                dates = job.get('dates', '')
                chunk.append(Paragraph(f"<b>{title}</b> | {company}", style_right_text))
                chunk.append(Paragraph(f"<i>{dates}</i>", style_right_text))
                for bullet in job.get('bullets', []):
                     chunk.append(Paragraph(f"• {bullet}", style_right_text))
                chunk.append(Spacer(1, 8))
                right_chunks.append(chunk)

        # 5. Projects (One chunk per project)
        if 'projects' in resume_data:
             right_chunks.append([Paragraph("PROJECTS", style_right_header)])
             for proj in resume_data['projects']:
                 chunk = []
                 name = proj.get('name', '')
                 desc = proj.get('description', '')
                 tech = proj.get('technologies', '')
                 chunk.append(Paragraph(f"<b>{name}</b> ({tech})", style_right_text))
                 chunk.append(Paragraph(desc, style_right_text))
                 chunk.append(Spacer(1, 8))
                 right_chunks.append(chunk)

        # 6. Co-curricular Activities
        if 'activities' in resume_data and resume_data['activities']:
            chunk = []
            chunk.append(Paragraph("CO-CURRICULAR ACTIVITIES", style_right_header))
            # Split by newline if multiple lines
            activities = resume_data['activities'].split('\n')
            for act in activities:
                if act.strip():
                    chunk.append(Paragraph(f"• {act.strip()}", style_right_text))
            chunk.append(Spacer(1, 8))
            right_chunks.append(chunk)

        # --- BUILD MULTI-ROW TABLE ---
        table_data = []
        
        # Pair up chunks using zip_longest
        for left, right in zip_longest(left_chunks, right_chunks, fillvalue=[]):
            # Check for None inputs from zip_longest if lists are unequal length
            # zip_longest fills with the fillvalue (empty list)
            table_data.append([left if left is not None else [], right if right is not None else []])
            
        col_widths = [sidebar_width, main_width] 
        
        t = Table(table_data, colWidths=col_widths)
        t.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BACKGROUND', (0,0), (0,-1), colors.Color(0.2, 0.2, 0.2)), # Dark Sidebar for Left Col
            # Padding simulates page margins
            ('LEFTPADDING', (0,0), (-1,-1), 20), # Sidebar content padding
            ('RIGHTPADDING', (0,0), (0,-1), 10), # Sidebar right padding
            ('LEFTPADDING', (1,0), (-1,-1), 20), # Main content padding
            ('RIGHTPADDING', (1,0), (-1,-1), 20), # Main content right padding
            ('TOPPADDING', (0,0), (-1,-1), 0), # Reduce row gaps
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        
        doc.build([t])
        buffer.seek(0)
        return buffer
        
    except Exception as e:
        print(f"Two Column PDF Error: {e}")
        # Build traceback
        import traceback
        traceback.print_exc()
        raise Exception(f"Two column PDF generation failed: {str(e)}")

def generate_zety_pdf(resume_data):
    """Generate a Zety-style PDF (Dark Sidebar)"""
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        styles = getSampleStyleSheet()
        
        # Colors
        dark_navy = colors.Color(0.17, 0.24, 0.31) # #2c3e50
        white = colors.white
        
        # Styles
        style_sidebar_header = ParagraphStyle('SidebarHead', parent=styles['Heading3'], textColor=white, spaceAfter=6, fontSize=11)
        style_sidebar_text = ParagraphStyle('SidebarText', parent=styles['Normal'], textColor=white, fontSize=9, leading=12)
        style_main_header = ParagraphStyle('MainHead', parent=styles['Heading2'], textColor=dark_navy, spaceAfter=8, borderPadding=0, spaceBefore=12)
        style_main_text = ParagraphStyle('MainText', parent=styles['BodyText'], fontSize=10, leading=14)
        style_name = ParagraphStyle('Name', parent=styles['Title'], textColor=dark_navy, alignment=0, spaceAfter=4, fontSize=26)
        style_role = ParagraphStyle('Role', parent=styles['Normal'], textColor=colors.gray, alignment=0, spaceAfter=12, fontSize=12)

        # --- LEFT (SIDEBAR) ---
        left_chunks = []
        
        # Contact
        if 'personal_info' in resume_data:
            info = resume_data['personal_info']
            if 'contact_info' in info:
                chunk = []
                chunk.append(Paragraph("<b>CONTACT</b>", style_sidebar_header))
                contacts = info['contact_info'].replace(' | ', '\n').replace(', ', '\n').replace(' • ', '\n').split('\n')
                for contact in contacts:
                    chunk.append(Paragraph(contact.strip(), style_sidebar_text))
                chunk.append(Spacer(1, 15))
                left_chunks.append(chunk)

        # Skills
        if 'skills' in resume_data:
            chunk = []
            chunk.append(Paragraph("<b>SKILLS</b>", style_sidebar_header))
            skills = resume_data['skills']
            if isinstance(skills, dict):
                 all_skills = skills.get('technical', []) + skills.get('soft', [])
            elif isinstance(skills, list):
                 all_skills = skills
            else:
                 all_skills = []
            
            for skill in all_skills[:12]: # Limit to prevent overflow
                chunk.append(Paragraph(f"• {skill}", style_sidebar_text))
            left_chunks.append(chunk)

        # --- RIGHT (MAIN) ---
        right_chunks = []
        
        # Header (Name position)
        if 'personal_info' in resume_data:
             info = resume_data['personal_info']
             name = info.get('name', 'Candidate')
             # We can add role if we had it, but resume_data structure matches what we have
             right_chunks.append([Paragraph(f"<b>{name.upper()}</b>", style_name)])

        # Summary
        if 'summary' in resume_data:
             chunk = []
             chunk.append(Paragraph("Summary", style_main_header))
             chunk.append(Paragraph(resume_data['summary'], style_main_text))
             right_chunks.append(chunk)

        # Experience
        if 'experience' in resume_data:
            chunk = []
            chunk.append(Paragraph("Experience", style_main_header))
            for job in resume_data['experience']:
                title = job.get('title', '')
                company = job.get('company', '')
                dates = job.get('dates', '')
                chunk.append(Paragraph(f"<b>{title}</b>", style_main_text))
                chunk.append(Paragraph(f"{company} | {dates}", style_main_text))
                for bullet in job.get('bullets', []):
                    chunk.append(Paragraph(f"• {bullet}", style_main_text))
                chunk.append(Spacer(1, 8))
            right_chunks.append(chunk)

        # Education
        if 'education' in resume_data:
            chunk = []
            chunk.append(Paragraph("Education", style_main_header))
            for edu in resume_data['education']:
                school = edu.get('school', '')
                degree = edu.get('degree', '')
                dates = edu.get('dates', '')
                chunk.append(Paragraph(f"<b>{degree}</b>", style_main_text))
                chunk.append(Paragraph(f"{school}, {dates}", style_main_text))
                chunk.append(Spacer(1, 8))
            right_chunks.append(chunk)

        # Build Table
        table_data = []
        for left, right in zip_longest(left_chunks, right_chunks, fillvalue=[]):
            table_data.append([left, right])
            
        t = Table(table_data, colWidths=[180, 400])
        t.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BACKGROUND', (0,0), (0,-1), dark_navy), # Dark Sidebar
            ('LEFTPADDING', (0,0), (-1,-1), 12),
            ('RIGHTPADDING', (0,0), (-1,-1), 12),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        
        doc.build([t])
        buffer.seek(0)
        return buffer
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise Exception(f"Zety PDF failed: {str(e)}")

def generate_harrison_pdf(resume_data):
    """Generate a Harrison-style PDF (Yellow Header)"""
    try:
        buffer = io.BytesIO()
        # Top margin bigger to accommodate header
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=140, leftMargin=40, rightMargin=40, bottomMargin=30)
        styles = getSampleStyleSheet()
        
        # Colors
        yellow = colors.Color(1, 0.88, 0.2) # #ffdf32 (approx Harrison yellow)
        black = colors.black
        
        # Styles
        style_section_head = ParagraphStyle('SecHead', parent=styles['Heading2'], textColor=black, 
                                          borderWidth=0, borderPadding=0, spaceAfter=8, spaceBefore=4,
                                          fontName='Helvetica-Bold', fontSize=10, textTransform='uppercase')
        
        # Section line/box (We will simulate with a drawing or just simple underline)
        # Harrison uses bold black lines.
        
        style_text = ParagraphStyle('Text', parent=styles['BodyText'], fontSize=10, leading=14, spaceAfter=4)
        style_bold = ParagraphStyle('BoldText', parent=styles['BodyText'], fontSize=10, leading=14, fontName='Helvetica-Bold')

        story = []
        
        # Helper for header drawing
        def draw_header(canvas, doc):
            canvas.saveState()
            # Draw Yellow Header Background
            canvas.setFillColor(yellow)
            canvas.rect(0, letter[1]-130, letter[0], 130, stroke=0, fill=1)
            
            # Draw Name
            canvas.setFillColor(black)
            canvas.setFont("Helvetica-Bold", 32)
            if 'personal_info' in resume_data:
                name = resume_data['personal_info'].get('name', 'NAME').upper()
                canvas.drawString(40, letter[1]-60, name)
                
                # Draw Role/Title (Mockup if not in data, or use contact)
                # resume_data doesn't stricly have 'role', we can use first job title or just leave empty
                contacts = resume_data['personal_info'].get('contact_info', '')
                canvas.setFont("Helvetica", 10)
                canvas.drawString(40, letter[1]-85, contacts)
                
                # Photo
                if 'photo_path' in resume_data['personal_info']:
                    p_path = resume_data['personal_info']['photo_path']
                    if p_path and os.path.exists(p_path):
                        try:
                            # Draw image on canvas directly
                            # Position: Right side of header
                            img_size = 100
                            canvas.drawImage(p_path, letter[0]-40-img_size, letter[1]-115, width=img_size, height=img_size, preserveAspectRatio=True, mask='auto')
                        except Exception as e:
                            print(f"Harrison photo error: {e}")

            canvas.restoreState()

        # Content - Single Column
        
        # Summary
        if 'summary' in resume_data:
            # We can use a Drawing Flowable for the thick black line, or just a Paragraph
            story.append(Paragraph("<b>PROFILE</b>", style_section_head))
            # Draw line?
            story.append(Paragraph(resume_data['summary'], style_text))
            story.append(Spacer(1, 15))
            
        # Experience
        if 'experience' in resume_data:
            story.append(Paragraph("<b>EMPLOYMENT HISTORY</b>", style_section_head))
            for job in resume_data['experience']:
                title = job.get('title', '')
                company = job.get('company', '')
                dates = job.get('dates', '')
                
                story.append(Paragraph(f"{title}, {company}", style_bold))
                story.append(Paragraph(dates.upper(), ParagraphStyle('Date', parent=style_text, fontSize=8, textColor=colors.gray)))
                
                for bullet in job.get('bullets', []):
                    story.append(Paragraph(f"• {bullet}", style_text))
                story.append(Spacer(1, 10))

        # Education
        if 'education' in resume_data:
            story.append(Paragraph("<b>EDUCATION</b>", style_section_head))
            for edu in resume_data['education']:
                school = edu.get('school', '')
                degree = edu.get('degree', '')
                dates = edu.get('dates', '')
                story.append(Paragraph(f"{degree}, {school}", style_bold))
                story.append(Paragraph(dates, style_text))
                story.append(Spacer(1, 5))

        # Skills
        if 'skills' in resume_data:
            story.append(Paragraph("<b>SKILLS</b>", style_section_head))
            skills = resume_data['skills']
            if isinstance(skills, dict):
                 tech = ", ".join(skills.get('technical', []))
                 soft = ", ".join(skills.get('soft', []))
                 if tech: story.append(Paragraph(f"<b>Technical:</b> {tech}", style_text))
                 if soft: story.append(Paragraph(f"<b>Soft:</b> {soft}", style_text))
            elif isinstance(skills, list):
                 story.append(Paragraph(", ".join(skills), style_text))

        doc.build(story, onFirstPage=draw_header, onLaterPages=draw_header)
        buffer.seek(0)
        return buffer
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise Exception(f"Harrison PDF failed: {str(e)}")

def generate_elegant_pdf(resume_data):
    """Generate an 'Elegant' PDF (Gray Header, Bordered)"""
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()
        
        # Colors
        gray_bg = colors.Color(0.95, 0.96, 0.97) # #f3f4f6
        dark_text = colors.Color(0.1, 0.1, 0.1)
        border_color = colors.Color(0.8, 0.8, 0.8)
        
        # Styles
        style_header_name = ParagraphStyle('HeadName', parent=styles['Title'], fontSize=24, alignment=1, textColor=dark_text, spaceAfter=4, fontName='Helvetica-Bold')
        style_header_title = ParagraphStyle('HeadTitle', parent=styles['Normal'], fontSize=12, alignment=1, textColor=colors.gray, spaceAfter=12, textTransform='uppercase', letterSpacing=1)
        style_header_contact = ParagraphStyle('HeadContact', parent=styles['Normal'], fontSize=9, alignment=1, textColor=dark_text)
        
        style_section = ParagraphStyle('Sec', parent=styles['Heading3'], fontSize=10, textColor=dark_text, 
                                     borderWidth=0, borderPadding=0, spaceAfter=8, spaceBefore=0, 
                                     fontName='Helvetica-Bold', textTransform='uppercase')
        
        style_item_title = ParagraphStyle('ItemTitle', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold', leading=12)
        style_item_sub = ParagraphStyle('ItemSub', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Oblique', textColor=colors.gray, leading=12)
        style_text = ParagraphStyle('Body', parent=styles['Normal'], fontSize=9, leading=13)
        
        story = []
        
        # --- HEADER SECTION (Gray Box) ---
        header_content = []
        if 'personal_info' in resume_data:
            info = resume_data['personal_info']
            name = info.get('name', 'CANDIDATE NAME').upper()
            contact = info.get('contact_info', '')
            
            header_content.append(Paragraph(name, style_header_name))
            header_content.append(Paragraph(contact, style_header_contact))
            
            # Photo for Elegant (Maybe small circle or box next to name? Or top center)
            if info.get('photo_path') and os.path.exists(info['photo_path']):
                try:
                    img = Image(info['photo_path'], width=80, height=80)
                    header_content.insert(0, img)
                    header_content.insert(1, Spacer(1, 10))
                except: pass
            
        header_table = Table([[header_content]], colWidths=[532]) # Full width (612 - 80 margin)
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), gray_bg),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('TOPPADDING', (0,0), (-1,-1), 20),
            ('BOTTOMPADDING', (0,0), (-1,-1), 20),
            ('BOX', (0,0), (-1,-1), 0.5, border_color), # Thin border
        ]))
        story.append(header_table)
        story.append(Spacer(1, 20))
        
        # --- BODY CONTENT ---
        left_chunks = []
        
        # Education (Left)
        if 'education' in resume_data:
            chunk = []
            chunk.append(Paragraph("EDUCATION", style_section))
            chunk.append(Spacer(1, 4))
            for edu in resume_data['education']:
                degree = edu.get('degree', '')
                school = edu.get('school', '')
                dates = edu.get('dates', '')
                chunk.append(Paragraph(degree, style_item_title))
                chunk.append(Paragraph(school, style_item_sub))
                chunk.append(Paragraph(dates, style_text))
                chunk.append(Spacer(1, 8))
            left_chunks.append(chunk)

        # Skills (Left)
        if 'skills' in resume_data:
            chunk = []
            chunk.append(Paragraph("SKILLS", style_section))
            chunk.append(Spacer(1, 4))
            skills = resume_data['skills']
            if isinstance(skills, dict):
                 tech = ", ".join(skills.get('technical', []))
                 soft = ", ".join(skills.get('soft', []))
                 if tech: 
                     chunk.append(Paragraph("Technical", style_item_title))
                     chunk.append(Paragraph(tech, style_text))
                     chunk.append(Spacer(1, 4))
                 if soft: 
                     chunk.append(Paragraph("Soft Skills", style_item_title))
                     chunk.append(Paragraph(soft, style_text))
            elif isinstance(skills, list):
                 chunk.append(Paragraph(", ".join(skills), style_text))
            left_chunks.append(chunk)
            
        right_chunks = []
        
        # Summary (Right)
        if 'summary' in resume_data:
            chunk = []
            chunk.append(Paragraph("PROFESSIONAL SUMMARY", style_section))
            chunk.append(Spacer(1, 4))
            chunk.append(Paragraph(resume_data['summary'], style_text))
            chunk.append(Spacer(1, 15))
            right_chunks.append(chunk)
            
        # Experience (Right)
        if 'experience' in resume_data:
            # Header
            right_chunks.append([Paragraph("WORK EXPERIENCE", style_section), Spacer(1, 4)])
            
            for job in resume_data['experience']:
                chunk = []
                title = job.get('title', '')
                company = job.get('company', '')
                dates = job.get('dates', '')
                
                chunk.append(Paragraph(title, style_item_title))
                chunk.append(Paragraph(f"{company} | {dates}", style_item_sub))
                
                for bullet in job.get('bullets', []):
                    chunk.append(Paragraph(f"• {bullet}", style_text))
                chunk.append(Spacer(1, 10))
                right_chunks.append(chunk)

        # Projects (Right)
        if 'projects' in resume_data and resume_data['projects']:
             right_chunks.append([Paragraph("PROJECTS", style_section), Spacer(1, 4)])
             for proj in resume_data['projects']:
                 chunk = []
                 name = proj.get('name', '')
                 desc = proj.get('description', '')
                 tech = proj.get('technologies', '')
                 chunk.append(Paragraph(name, style_item_title))
                 chunk.append(Paragraph(f"({tech})", style_item_sub))
                 chunk.append(Paragraph(desc, style_text))
                 chunk.append(Spacer(1, 8))
                 right_chunks.append(chunk)

        # Assemble Two-Column Body
        body_data = []
        for left, right in zip_longest(left_chunks, right_chunks, fillvalue=[]):
            body_data.append([left, right])
            
        body_table = Table(body_data, colWidths=[180, 340])
        body_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (0,-1), 20), # Padding between columns
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('LINEAFTER', (0,0), (0,-1), 0.5, border_color),
        ]))
        
        story.append(body_table)
        
        doc.build(story)
        buffer.seek(0)
        return buffer
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise Exception(f"Elegant PDF failed: {str(e)}")

def generate_two_column_pdf(resume_data, accent_color=colors.teal):
    """Generate a Two-Column Modern PDF Resume with Pagination Fix"""
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        styles = getSampleStyleSheet()
        
        # Custom Styles
        style_left_header = ParagraphStyle('LeftHeader', parent=styles['Heading3'], textColor=colors.white, spaceAfter=8)
        style_left_text = ParagraphStyle('LeftText', parent=styles['Normal'], textColor=colors.white, fontSize=9, leading=12)
        style_right_header = ParagraphStyle('RightHeader', parent=styles['Heading3'], textColor=accent_color, spaceAfter=8, borderPadding=0)
        style_right_text = ParagraphStyle('RightText', parent=styles['BodyText'], fontSize=10, leading=14)
        style_name = ParagraphStyle('Name', parent=styles['Title'], textColor=accent_color, alignment=0, spaceAfter=10, fontSize=24)
        
        # --- LEFT COLUMN CHUNKS ---
        left_chunks = []
        
        # 1. Contact Info
        if 'personal_info' in resume_data:
            info = resume_data['personal_info']
            if 'contact_info' in info:
                chunk = []
                chunk.append(Paragraph("<b>CONTACT</b>", style_left_header))
                contacts = info['contact_info'].replace(' | ', '\n').replace(', ', '\n').split('\n')
                for contact in contacts:
                    chunk.append(Paragraph(contact, style_left_text))
                chunk.append(Spacer(1, 15))
                left_chunks.append(chunk)

        # 2. Skills
        if 'skills' in resume_data:
            chunk = []
            chunk.append(Paragraph("<b>SKILLS</b>", style_left_header))
            skills = resume_data['skills']
            if isinstance(skills, dict):
                if 'technical' in skills:
                    chunk.append(Paragraph("<b>Technical:</b>", style_left_text))
                    for skill in skills['technical']:
                        chunk.append(Paragraph(f"• {skill}", style_left_text))
                    chunk.append(Spacer(1, 5))
                if 'soft' in skills:
                    chunk.append(Paragraph("<b>Soft:</b>", style_left_text))
                    for skill in skills['soft']:
                         chunk.append(Paragraph(f"• {skill}", style_left_text))
            elif isinstance(skills, list):
                for skill in skills:
                    chunk.append(Paragraph(f"• {skill}", style_left_text))
            chunk.append(Spacer(1, 15))
            left_chunks.append(chunk)

        # 3. Education
        if 'education' in resume_data:
            chunk = []
            chunk.append(Paragraph("<b>EDUCATION</b>", style_left_header))
            for edu in resume_data['education']:
                school = edu.get('school', '')
                degree = edu.get('degree', '')
                dates = edu.get('dates', '')
                chunk.append(Paragraph(f"<b>{school}</b>", style_left_text))
                chunk.append(Paragraph(degree, style_left_text))
                chunk.append(Paragraph(dates, style_left_text))
                chunk.append(Spacer(1, 8))
            left_chunks.append(chunk)
        
        # --- RIGHT COLUMN CHUNKS ---
        right_chunks = []
        
        # 1. Name
        if 'personal_info' in resume_data:
             name = resume_data['personal_info'].get('name', 'Candidate')
             right_chunks.append([Paragraph(name.upper(), style_name)])
        
        # 2. Summary
        if 'summary' in resume_data:
            chunk = []
            chunk.append(Paragraph("PROFESSIONAL SUMMARY", style_right_header))
            chunk.append(Paragraph(resume_data['summary'], style_right_text))
            chunk.append(Spacer(1, 12))
            right_chunks.append(chunk)
            
        # 3. Experience (One chunk per job to allow splitting)
        if 'experience' in resume_data:
            # Header
            right_chunks.append([Paragraph("EXPERIENCE", style_right_header)])
            
            for job in resume_data['experience']:
                chunk = []
                title = job.get('title', '')
                company = job.get('company', '')
                dates = job.get('dates', '')
                chunk.append(Paragraph(f"<b>{title}</b> | {company}", style_right_text))
                chunk.append(Paragraph(f"<i>{dates}</i>", style_right_text))
                for bullet in job.get('bullets', []):
                     chunk.append(Paragraph(f"• {bullet}", style_right_text))
                chunk.append(Spacer(1, 8))
                right_chunks.append(chunk)

        # 4. Projects (One chunk per project)
        if 'projects' in resume_data:
             right_chunks.append([Paragraph("PROJECTS", style_right_header)])
             for proj in resume_data['projects']:
                 chunk = []
                 name = proj.get('name', '')
                 desc = proj.get('description', '')
                 tech = proj.get('technologies', '')
                 chunk.append(Paragraph(f"<b>{name}</b> ({tech})", style_right_text))
                 chunk.append(Paragraph(desc, style_right_text))
                 chunk.append(Spacer(1, 8))
                 right_chunks.append(chunk)

        # --- BUILD MULTI-ROW TABLE ---
        table_data = []
        
        # Pair up chunks using zip_longest
        for left, right in zip_longest(left_chunks, right_chunks, fillvalue=[]):
            table_data.append([left, right])
            
        col_widths = [180, 400] 
        
        t = Table(table_data, colWidths=col_widths)
        t.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BACKGROUND', (0,0), (0,-1), colors.Color(0.2, 0.2, 0.2)), # Dark Sidebar for Left Col
            ('LEFTPADDING', (0,0), (-1,-1), 12),
            ('RIGHTPADDING', (0,0), (-1,-1), 12),
            ('TOPPADDING', (0,0), (-1,-1), 0), # Tight packing
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        
        doc.build([t])
        buffer.seek(0)
        return buffer
        
    except Exception as e:
        print(f"Two Column PDF Error: {e}")
        # Build traceback
        import traceback
        traceback.print_exc()
        raise Exception(f"Two column PDF generation failed: {str(e)}")


def generate_brand_new_pdf(resume_data, template_name='classic'):
    """Generate a PDF from the structured resume data"""
    
    # Route to Specific Template Functions
    if template_name == 'modern':
        return generate_two_column_pdf(resume_data, accent_color=colors.teal)
    elif template_name == 'zety':
        return generate_zety_pdf(resume_data)
    elif template_name == 'harrison':
        return generate_harrison_pdf(resume_data)
    elif template_name == 'elegant':
        return generate_elegant_pdf(resume_data)
    elif template_name == 'bank':
        # Map generic resume data to Bank/ATS format
        ats_data = {
            'contact_info': {
                'name': resume_data.get('personal_info', {}).get('name', ''),
                # details are in a single string in generic format, pass as-is or specific parsing?
                # For now, put the whole string in 'email' or split if possible. 
                # Better: simple mapping, let the template handle display or minimal parsing.
                'email': resume_data.get('personal_info', {}).get('contact_info', ''), 
                'phone': '', # Included in contact_info string above
                'location': '' 
            },
            'professional_summary': resume_data.get('summary', ''),
            'experience': [],
            'education': [],
            'skills': {
                'erp_and_tools': [],
                'domain_knowledge': []
            }
        }
        
        # Map Experience
        for exp in resume_data.get('experience', []):
            ats_data['experience'].append({
                'company': exp.get('company', ''),
                'title': exp.get('title', ''),
                'duration': exp.get('dates', ''),
                'achievements': exp.get('bullets', [])
            })
            
        # Map Education
        for edu in resume_data.get('education', []):
            ats_data['education'].append({
                'degree': edu.get('degree', ''),
                'institution': edu.get('school', ''),
                'year': edu.get('dates', ''),
                'score': ''
            })
            
        # Map Skills
        skills = resume_data.get('skills', {})
        if isinstance(skills, dict):
            ats_data['skills']['erp_and_tools'] = skills.get('technical', [])
            ats_data['skills']['domain_knowledge'] = skills.get('soft', [])
        elif isinstance(skills, list):
            ats_data['skills']['erp_and_tools'] = skills
            
        # Generate with xhtml2pdf (reusing logic from generate_ats_pdf but inline or separate call)
        # We can just call generate_ats_pdf(ats_data)!
        return generate_ats_pdf(ats_data)
        
    # Define styles based on other templates (Classic / Creative)
    if template_name == 'creative':
        accent_color = colors.Color(0.5, 0, 0.5) # Purple
        title_alignment = 0 # Left
    else: # Classic
        accent_color = colors.Color(0.145, 0.388, 0.922) # #2563eb
        title_alignment = 0 # Left

    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        # Heading Style
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            textColor=accent_color,
            borderPadding=5,
            borderColor=accent_color,
            borderWidth=0,
            borderBottomWidth=1,
            spaceAfter=12,
            alignment=title_alignment
        )
        
        # Title Style
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Title'],
            alignment=title_alignment,
            spaceAfter=12
        )

        # Header
        if 'personal_info' in resume_data:
            info = resume_data['personal_info']
            name = info.get('name', '')
            contact = info.get('contact_info', '')
            
            story.append(Spacer(1, 12))

            # Photo (Top Right or Center? Let's put it above name if exists for now, or use a Table for header)
            if info.get('photo_path') and os.path.exists(info['photo_path']):
                try:
                    img = Image(info['photo_path'], width=100, height=100)
                    img.hAlign = 'LEFT' if title_alignment == 0 else 'CENTER' # Match title
                    story.append(img)
                    story.append(Spacer(1, 10))
                except: pass

            # Standard Font (Helvetica) for ATS
            story.append(Paragraph(f"<b>{name}</b>", title_style))
            story.append(Paragraph(contact, styles['Normal']))
            story.append(Spacer(1, 12))

        # Summary
        if 'summary' in resume_data:
            story.append(Paragraph("<b>Professional Summary</b>", heading_style)) 
            story.append(Paragraph(resume_data['summary'], styles['BodyText']))
            story.append(Spacer(1, 12))
        
        # Skills
        if 'skills' in resume_data:
            story.append(Paragraph("<b>Skills</b>", heading_style)) 
            skills = resume_data['skills']
            if isinstance(skills, dict):
                tech = ", ".join(skills.get('technical', []))
                soft = ", ".join(skills.get('soft', []))
                # Simple list format is best for ATS
                if tech: story.append(Paragraph(f"<b>Technical:</b> {tech}", styles['Normal']))
                if soft: story.append(Paragraph(f"<b>Soft:</b> {soft}", styles['Normal']))
            elif isinstance(skills, list):
                story.append(Paragraph(", ".join(skills), styles['Normal']))
            story.append(Spacer(1, 12))

        # Experience
        if 'experience' in resume_data:
            story.append(Paragraph("<b>Experience</b>", heading_style))
            for job in resume_data['experience']:
                title = job.get('title', '')
                company = job.get('company', '')
                dates = job.get('dates', '')
                # Clean format: Title at Company | Dates
                # We can also color the Title
                header = f"<b><font color={accent_color}>{title}</font></b> at {company} | {dates}"
                story.append(Paragraph(header, styles['Normal']))
                for bullet in job.get('bullets', []):
                    story.append(Paragraph(f"• {bullet}", styles['BodyText']))
                story.append(Spacer(1, 6))
        
        # Education
        if 'education' in resume_data:
            story.append(Paragraph("<b>Education</b>", heading_style))
            for edu in resume_data['education']:
                 degree = edu.get('degree', '')
                 school = edu.get('school', '')
                 dates = edu.get('dates', '')
                 story.append(Paragraph(f"{degree}, {school} - {dates}", styles['Normal']))
            story.append(Spacer(1, 12))

        # Projects
        if 'projects' in resume_data and resume_data['projects']:
            story.append(Paragraph("<b>Projects</b>", heading_style)) 
            for proj in resume_data['projects']:
                 name = proj.get('name', '')
                 desc = proj.get('description', '')
                 tech = proj.get('technologies', '')
                 story.append(Paragraph(f"<b><font color={accent_color}>{name}</font></b> ({tech})", styles['Normal']))
                 story.append(Paragraph(desc, styles['BodyText']))
                 story.append(Spacer(1, 6))
        
        doc.build(story)
            
        buffer.seek(0)
        return buffer
    except Exception as e:
        raise Exception(f"New PDF generation failed: {str(e)}")

def generate_ats_pdf(data):
    """Generate ATS-optimized PDF using xhtml2pdf"""
    try:
        # Render HTML template
        html_content = render_template('bank_resume.html', **data)
        
        # Create PDF
        buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(html_content, dest=buffer)
        
        if pisa_status.err:
            raise Exception("PDF generation error")
            
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f"ATS PDF Error: {e}")
        import traceback
        traceback.print_exc()
        raise Exception(f"ATS PDF generation failed: {str(e)}")


# ============================================================================
# ROUTES
# ============================================================================



# ============================================================================
# AUTH ROUTES
# ============================================================================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        
        users = load_users()
        
        if username in users:
            return render_template('register.html', error="Username already exists")
            
        # Create user record
        users[username] = {
            'username': username,
            'email': email,
            'user_id': str(uuid.uuid4())
        }
        
        # Password hashing
        if hasattr(ws, 'generate_password_hash'):
            users[username]['password'] = ws.generate_password_hash(password)
        else:
            users[username]['password'] = password

        save_users(users)
        session['user'] = users[username]
        return redirect(url_for('dashboard'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        users = load_users()
        
        if username not in users:
            return render_template('login.html', error="User not found")
            
        user = users[username]
        
        # Verify password
        if hasattr(ws, 'check_password_hash'):
            # Only use check_password_hash if the stored password looks like a hash (starts with method$)
            # or if we are sure. For simplicity in this mix environment:
            try:
                is_valid = ws.check_password_hash(user['password'], password)
            except:
                is_valid = user['password'] == password
        else:
            is_valid = user['password'] == password

        if is_valid:
            session['user'] = user
            return redirect(url_for('dashboard'))
        else:
             return render_template('login.html', error="Invalid password")
             
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=session['user'])

@app.route('/history')
@login_required
def history():
    all_history = load_history()
    user_history = [h for h in all_history if h.get('user_id') == session['user']['user_id']]
    return render_template('history.html', user=session['user'], history=user_history)

@app.route('/download/<filename>')
@login_required
def download_file(filename):
    # Security check: ensure file is in output folder
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)

@app.route('/')
def index():
    """Root URL - Redirect to Dashboard or Login"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/create', methods=['GET', 'POST'])
def create_resume():
    """Manual Resume Creation"""
    if request.method == 'POST':
        try:
            # Logic to extract form data and create JSON
            data = {
                'doc_type': request.form.get('doc_type', 'resume'), # Track if CV or Resume
                'personal_info': {
                    'name': request.form.get('name'),
                    'email': request.form.get('email'),
                    'phone': request.form.get('phone'),
                    'contact_info': f"{request.form.get('email')} | {request.form.get('phone')} | {request.form.get('links', '')}",
                    'photo_path': None
                },
                'summary': request.form.get('summary'),
                'career_objective': request.form.get('career_objective'),
                'skills': {
                    'technical': [s.strip() for s in request.form.get('technical_skills', '').split(',') if s.strip()],
                    'soft': [s.strip() for s in request.form.get('soft_skills', '').split(',') if s.strip()]
                },
                'languages': [l.strip() for l in request.form.get('languages', '').split(',') if l.strip()],
                'activities': request.form.get('activities'), # Keep as text for now, or split if newline
                'experience': [],
                'education': [],
                'projects': [],
                'certifications': []
            }

            # Handle Profile Photo
            if 'profile_photo' in request.files:
                photo = request.files['profile_photo']
                if photo and photo.filename != '':
                    filename = secure_filename(f"photo_{uuid.uuid4()}_{photo.filename}")
                    photo_dir = os.path.join('static', 'uploads', 'photos')
                    os.makedirs(photo_dir, exist_ok=True)
                    photo_path = os.path.join(photo_dir, filename)
                    photo.save(photo_path)
                    data['personal_info']['photo_path'] = photo_path

            # Extract dynamic lists
            titles = request.form.getlist('exp_title[]')
            companies = request.form.getlist('exp_company[]')
            dates = request.form.getlist('exp_dates[]')
            descs = request.form.getlist('exp_desc[]')
            
            for i in range(len(titles)):
                data['experience'].append({
                    'title': titles[i],
                    'company': companies[i],
                    'dates': dates[i],
                    'bullets': [b.strip() for b in descs[i].split('\n') if b.strip()]
                })

            degrees = request.form.getlist('edu_degree[]')
            schools = request.form.getlist('edu_school[]')
            edates = request.form.getlist('edu_dates[]')
            escores = request.form.getlist('edu_score[]')

            # Handle case where score might be missing in older submitted forms (unlikely here but good practice)
            # Since getlist returns all values, and the input is in the loop, if we add it to the form it should match.
            # However, if array lengths differ, we should handle it safely.
            
            for i in range(len(degrees)):
                score = escores[i] if i < len(escores) else ""
                data['education'].append({
                    'degree': degrees[i],
                    'school': schools[i],
                    'dates': edates[i],
                    'score': score
                })

            pnames = request.form.getlist('proj_name[]')
            ptech = request.form.getlist('proj_tech[]')
            pdesc = request.form.getlist('proj_desc[]')

            for i in range(len(pnames)):
                data['projects'].append({
                    'name': pnames[i],
                    'technologies': ptech[i],
                    'description': pdesc[i]
                })

            cnames = request.form.getlist('cert_name[]')
            cauths = request.form.getlist('cert_auth[]')
            cyears = request.form.getlist('cert_year[]')

            for i in range(len(cnames)):
                data['certifications'].append({
                    'name': cnames[i],
                    'authority': cauths[i],
                    'year': cyears[i]
                })

            # Store data in session (optional, for editing later if needed)
            session['resume_data'] = data
            
            # Save generated data to file for the Tailored Resume view
            gen_id = str(uuid.uuid4())
            gen_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"gen_{gen_id}.json")
            with open(gen_file, 'w') as f:
                json.dump(data, f)
            
            # Redirect to the Tailored Resume page (Combined View)
            return redirect(url_for('show_generated_resume', gen_id=gen_id))

        except Exception as e:
            print(f"Create Resume Error: {e}")
            return f"Error creating resume: {str(e)}", 500

    # GET Request - Check for pre-fill data
    prefill_data = session.pop('prefill_data', None)
    if not prefill_data and 'resume_data' in session:
        prefill_data = session.get('resume_data')

    doc_type = request.args.get('doc_type', 'resume')
    
    # Only use pre-fill data if it matches the requested document type
    if prefill_data and prefill_data.get('doc_type') != doc_type:
        prefill_data = None
    
    # If prefill_data exists (and matches), ensure doc_type is consistent (redundant but safe)
    if prefill_data and 'doc_type' in prefill_data:
        doc_type = prefill_data['doc_type']
    
    return render_template('create.html', prefill=prefill_data, doc_type=doc_type)


@app.route('/select-template')
def select_template():
    """Render the template selection page"""
    if 'resume_data' not in session:
        return redirect(url_for('create_resume'))
    
    resume_data = session.get('resume_data')
    doc_type = resume_data.get('doc_type', 'resume')
    
    return render_template('select_template.html', doc_type=doc_type, resume_data=resume_data)


@app.route('/generate-resume', methods=['POST'])
def generate_resume():
    """Generate the resume with the selected template"""
    try:
        resume_data = session.get('resume_data')
        
        if not resume_data:
            return redirect(url_for('create_resume'))
            
        template_name = request.form.get('template_name', 'modern')
        print(f"[DEBUG] Generating resume with template: {template_name}")
        
        # Call the existing generation logic
        pdf_buffer = generate_brand_new_pdf(resume_data, template_name)
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"Resume_{resume_data['personal_info']['name'].replace(' ', '_')}_{template_name}.pdf"
        )
        
    except Exception as e:
        print(f"Generation Error: {e}")
        import traceback
        traceback.print_exc()
        return f"Error generating resume: {str(e)}", 500


@app.route('/upload-home', methods=['GET', 'POST'])
def upload_home():
    """Handle Resume Generation (Home Page) & Import"""
    if request.method == 'POST':
        try:
            # File validation
            if 'resume' not in request.files:
                return jsonify({'error': 'No resume file uploaded'}), 400
            file = request.files['resume']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
            if not allowed_file(file.filename):
                return jsonify({'error': 'Invalid file type'}), 400
            
            # Check for Import Mode
            doc_type = request.form.get('doc_type')
            if doc_type:
                # IMPORT FLOW
                target_role = request.form.get('target_role')
                
                filename = secure_filename(file.filename)
                unique_filename = f"import_{uuid.uuid4()}_{filename}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(filepath)
                
                try:
                    resume_text = extract_text_from_pdf(filepath)
                    # Use AI to parse into our schema
                    # We need a specific prompt for this
                    parsed_data = parse_resume_to_json(resume_text, target_role=target_role)
                    
                    session['prefill_data'] = parsed_data
                    return jsonify({
                        'success': True,
                        'redirect': url_for('create_resume', doc_type=doc_type)
                    })
                    
                except Exception as e:
                    print(f"Import Error: {e}")
                    return jsonify({'error': f"Failed to parse resume: {e}"}), 500

            # ATS ANALYSIS FLOW (Existing)
            print(f"[DEBUG] Processing new resume generation request: {file.filename}")
            
            job_description = request.form.get('job_description', '').strip()
            # ... (rest of existing logic)
            if not job_description and not doc_type: 
                 pass # Allow empty JD for pure analysis if needed, or enforce

            # Get ATS Mode preference
            ats_mode = request.form.get('ats_mode') == 'on' # Checkbox sends 'on' if checked

            # Save and extract
            filename = secure_filename(file.filename)
            unique_filename = f"gen_{uuid.uuid4()}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(filepath)
            
            try:
                resume_text = extract_text_from_pdf(filepath)
                # Sanitize the text
                resume_text = sanitize_resume_data(resume_text)
            except Exception as e:
                return jsonify({'error': 'Failed to read PDF'}), 500
            
            # Generate or Analyze based on button? 
            # The original code here called `generate_custom_resume` which seems to be the "Analyze" flow 
            # based on `upload_home.html` saying "Analyze Resume". 
            # Wait, the previous code was:
            # generated_data = generate_custom_resume(resume_text, job_description)
            # This returned structured advice, not a new resume PDF directly.
            
            print("[DEBUG] Starting AI generation...")
            generated_data = generate_custom_resume(resume_text, job_description)
            print("[DEBUG] AI generation successful.")
            
            # Save generated data
            gen_id = str(uuid.uuid4())
            gen_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"gen_{gen_id}.json")
            with open(gen_file, 'w') as f:
                json.dump(generated_data, f)
            
            return jsonify({
                'success': True,
                'redirect': url_for('show_generated_resume', gen_id=gen_id)
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500
            
    return render_template('upload_home.html')

def parse_resume_to_json(text, target_role=None):
    """Refine raw text into structured JSON for the create form using Groq"""
    if not client: return {}
    
    context_instruction = ""
    if target_role:
        context_instruction = f"IMPORTANT: The user is targeting the role of '{target_role}'. Rewrite the 'career_objective' and 'summary' to be specifically tailored for this position, emphasizing relevant skills from the resume."

    prompt = f"""
    Extract the following information from the resume text below and return ONLY valid JSON.
    {context_instruction}
    
    Schema:
    {{
        "personal_info": {{
            "name": "...",
            "email": "...",
            "phone": "...",
            "links": "..." 
        }},
        "summary": "...",
        "career_objective": "...",
        "skills": {{
            "technical": ["..."],
            "soft": ["..."]
        }},
        "languages": ["..."],
        "experience": [
            {{ "title": "...", "company": "...", "dates": "...", "bullets": ["..."] }}
        ],
        "education": [
            {{ "degree": "...", "school": "...", "dates": "...", "score": "..." }}
        ],
        "projects": [
             {{ "name": "...", "technologies": "...", "description": "..." }}
        ],
        "certifications": [
            {{ "name": "...", "authority": "...", "year": "..." }}
        ],
        "activities": "..."
    }}
    
    Resume Text:
    {text[:4000]}
    """
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"Parsing error: {e}")
        return {}


@app.route('/tips')
def tips():
    """Resume tips and best practices page"""
    return render_template('tips.html')


@app.route('/clear-session')
def clear_session():
    """Clear current session and analysis data"""
    # Clean up uploaded files and analysis data
    if 'current_analysis_id' in session:
        analysis_id = session['current_analysis_id']
        analysis_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"{analysis_id}.json")
        
        # Load and delete associated files
        try:
            with open(analysis_file, 'r') as f:
                analysis = json.load(f)
            filepath = analysis.get('filepath')
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
            os.remove(analysis_file)
        except:
            pass
    
    session.clear()
    return redirect(url_for('index'))


@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors"""
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(e):
    """Handle 500 errors"""
    return render_template('500.html'), 500


@app.errorhandler(413)
def too_large(e):
    """Handle file too large errors"""
    return jsonify({'error': 'File too large. Maximum size is 16MB.'}), 413


# ============================================================================
# CHATBOT ROUTE
# ============================================================================

@app.route('/chat', methods=['POST'])
def chat():
    """Handle Chatbot Requests"""
    try:
        data = request.json
        user_message = data.get('message', '')
        
        if not user_message:
            return jsonify({'error': 'No message provided'}), 400

        if not client:
            return jsonify({'error': 'Groq client not initialized'}), 500

        # Context for the AI
        system_context = """
        You are the "ATS Checker Assistant", a helpful AI embedded in a Resume Analysis application.
        Your goal is to help users improve their resumes and understand how ATS (Applicant Tracking Systems) work.
        
        Capabilities of this app:
        - Analyze resumes against job descriptions.
        - Give ATS scores.
        - Suggest improvements.
        - Generate AI-enhanced PDFs.
        
        Keep your answers concise, encouraging, and professional. 
        If asked about things unrelated to career, resumes, or job hunting, politely steer back to those topics.
        """
        
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_context},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_tokens=1024,
            stream=False
        )
        
        return jsonify({
            'response': completion.choices[0].message.content
        })

    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({'error': 'Sorry, I am having trouble thinking right now. Please try again.'}), 500


# ============================================================================
# CLEANUP TASK (Optional - runs periodically)
# ============================================================================

def cleanup_old_files():
    """Remove uploaded files and analysis data older than 1 hour"""
    try:
        current_time = datetime.now().timestamp()
        
        # Clean uploads folder
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.isfile(filepath):
                file_time = os.path.getmtime(filepath)
                # Delete files older than 1 hour
                if current_time - file_time > 3600:
                    os.remove(filepath)
        
        # Clean analysis data folder
        for filename in os.listdir(app.config['ANALYSIS_FOLDER']):
            filepath = os.path.join(app.config['ANALYSIS_FOLDER'], filename)
            if os.path.isfile(filepath):
                file_time = os.path.getmtime(filepath)
                # Delete files older than 1 hour
                if current_time - file_time > 3600:
                    os.remove(filepath)
    except Exception as e:
        print(f"Cleanup error: {e}")


# ============================================================================
# FEEDBACK ROUTE
# ============================================================================

@app.route('/feedback', methods=['POST'])
def submit_feedback():
    """Handle User Feedback Submission"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        feedback_entry = {
            'id': str(uuid.uuid4()),
            'timestamp': datetime.now().isoformat(),
            'rating': data.get('rating'),
            'comment': data.get('comment', '').strip(),
            'page': data.get('page', 'unknown')
        }
        
        feedback_file = 'feedback.json'
        
        # Load existing feedback
        existing_feedback = []
        if os.path.exists(feedback_file):
            try:
                with open(feedback_file, 'r') as f:
                    existing_feedback = json.load(f)
            except:
                pass # Start fresh if file is corrupt
        
        # Append new feedback
        existing_feedback.append(feedback_entry)
        
        # Save back to file
        with open(feedback_file, 'w') as f:
            json.dump(existing_feedback, f, indent=2)
            
        return jsonify({'success': True, 'message': 'Thank you for your feedback!'})
        
    except Exception as e:
        print(f"Feedback error: {e}")
        return jsonify({'error': 'Failed the submit feedback'}), 500




@app.route('/generated-resume/<gen_id>')
def show_generated_resume(gen_id):
    """View generated resume"""
    gen_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"gen_{gen_id}.json")
    try:
        with open(gen_file, 'r') as f:
            data = json.load(f)
        return render_template('generated_resume.html', resume=data, gen_id=gen_id)
    except FileNotFoundError:
        return redirect(url_for('dashboard'))

@app.route('/download-generated-pdf/<gen_id>')
def download_generated_pdf(gen_id):
    """Download generated resume as PDF"""
    gen_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"gen_{gen_id}.json")
    try:
        template = request.args.get('template', 'classic')
        with open(gen_file, 'r') as f:
            data = json.load(f)
        # Use saved accent color if available
        pdf_buffer = generate_brand_new_pdf(data, template_name=template)
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'Tailored_Resume_{template}.pdf'
        )
    except Exception as e:
        return f"Error: {str(e)}", 500


@app.route('/download-enhanced-resume/<analysis_id>')
def download_enhanced_resume(analysis_id):
    """Download AI-enhanced resume PDF"""
    analysis_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"ats_{analysis_id}.json")
    try:
        with open(analysis_file, 'r') as f:
            data = json.load(f)
        
        # Try to get original text
        original_text = ""
        if 'filepath' in data:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], data['filepath'])
            if os.path.exists(filepath):
                try:
                    original_text = extract_text_from_pdf(filepath)
                except:
                    pass
        
        pdf_buffer = generate_enhanced_pdf(data, original_text)
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='Enhanced_Resume.pdf'
        )
    except Exception as e:
        # Improved error visibility
        print(f"Download Error: {e}")
        return f"Error generating PDF: {str(e)}", 500


@app.route('/analyze-jd', methods=['GET', 'POST'])
def analyze_jd():
    """Handle Job Description Analysis"""
    if request.method == 'POST':
        try:
            job_description = request.form.get('job_description', '').strip()
            if not job_description:
                return jsonify({'error': 'Job description is required'}), 400

            # Analyze JD
            analysis_result = analyze_job_description_with_ai(job_description)
            
            # Save analysis
            jd_id = str(uuid.uuid4())
            jd_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"jd_{jd_id}.json")
            with open(jd_file, 'w') as f:
                json.dump(analysis_result, f)
            
            return jsonify({
                'success': True,
                'redirect': url_for('show_jd_result', jd_id=jd_id)
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500
            
    return render_template('analyze_jd.html')

@app.route('/jd-result/<jd_id>')
def show_jd_result(jd_id):
    """View JD analysis result"""
    jd_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"jd_{jd_id}.json")
    try:
        with open(jd_file, 'r') as f:
            data = json.load(f)
        return render_template('jd_analysis_result.html', analysis=data)
    except FileNotFoundError:
        return redirect(url_for('analyze_jd'))

@app.route('/enhance-content', methods=['GET', 'POST'])
def enhance_content():
    """Handle Content Enhancement"""
    if request.method == 'POST':
        try:
            data = request.get_json()
            text = data.get('content', '').strip()
            style = data.get('style', 'Professional')

            if not text:
                return jsonify({'error': 'Content is required'}), 400

            improved_content = rewrite_resume_section(text, style)
            
            return jsonify({
                'success': True,
                'original': text,
                'improved': improved_content
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500
            
    return render_template('enhance_content.html')


@app.route('/rewrite-section', methods=['POST'])
def rewrite_section_route():
    """Handle AI Rewrite for Dashboard"""
    try:
        data = request.get_json()
        section = data.get('section', '')
        content = data.get('content', '').strip()
        
        if not content:
            return jsonify({'error': 'No content provided'}), 400

        # Rewrite the content
        improved_content = rewrite_resume_section(content, improvement_type="Professional")
        
        return jsonify({
            'success': True,
            'improved_content': improved_content
        })

    except Exception as e:
        print(f"Rewrite Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/analyze-resume', methods=['POST'])
def analyze_resume():
    """Handle Resume Analysis (ATS Checker)"""
    try:
        # File validation
        if 'resume' not in request.files:
            return jsonify({'error': 'No resume file uploaded'}), 400
        file = request.files['resume']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        
        job_description = request.form.get('job_description', '').strip()
        # JD is optional for pure ATS check, but better if provided
        
        # Save and extract
        filename = secure_filename(file.filename)
        unique_filename = f"ats_{uuid.uuid4()}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)
        
        try:
            resume_text = extract_text_from_pdf(filepath)
            # Sanitize the text
            resume_text = sanitize_resume_data(resume_text)
        except Exception as e:
            return jsonify({'error': 'Failed to read PDF'}), 500
        
        # Analyze
        analysis_result = analyze_with_groq(resume_text, job_description)
        
        # Add metadata
        analysis_result['filename'] = filename
        analysis_result['filepath'] = unique_filename
        analysis_result['timestamp'] = datetime.now().isoformat()
        analysis_result['job_description'] = job_description

        
        # Save analysis
        analysis_id = str(uuid.uuid4())
        analysis_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"ats_{analysis_id}.json")
        with open(analysis_file, 'w') as f:
            json.dump(analysis_result, f)
            
        return jsonify({
            'success': True,
            'redirect': url_for('show_dashboard', analysis_id=analysis_id)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/dashboard/<analysis_id>')
def show_dashboard(analysis_id):
    """View Analysis Dashboard"""
    analysis_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"ats_{analysis_id}.json")
    try:
        with open(analysis_file, 'r') as f:
            data = json.load(f)
        return render_template(
            'analysis_result.html', 
            analysis=data, 
            filename=data.get('filename', 'Resume.pdf'),
            timestamp=data.get('timestamp', ''),
            analysis_id=analysis_id,
            user=session.get('user')
        )
    except FileNotFoundError:
        return redirect(url_for('index'))


@app.route('/generate-tailored-from-analysis/<analysis_id>', methods=['POST'])
def generate_tailored_from_analysis(analysis_id):
    """Generate a tailored resume JSON from existing analysis data and redirect to generated_resume"""
    try:
        analysis_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"ats_{analysis_id}.json")
        with open(analysis_file, 'r') as f:
            data = json.load(f)
            
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], data.get('filepath', ''))
        job_description = data.get('job_description', '')
        
        if not os.path.exists(filepath):
            return jsonify({'error': 'Original PDF not found'}), 404
            
        resume_text = extract_text_from_pdf(filepath)
        resume_text = sanitize_resume_data(resume_text)
        
        generated_data = generate_custom_resume(resume_text, job_description)
        
        # Save generated data
        gen_id = str(uuid.uuid4())
        gen_file = os.path.join(app.config['ANALYSIS_FOLDER'], f"gen_{gen_id}.json")
        with open(gen_file, 'w') as f:
            json.dump(generated_data, f)
            
        return jsonify({
            'success': True,
            'redirect': url_for('show_generated_resume', gen_id=gen_id)
        })

    except Exception as e:
        print(f"Tailored generation error: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# RUN APPLICATION
# ============================================================================

if __name__ == '__main__':
    # Run cleanup on startup
    cleanup_old_files()
    
    # Start Flask application
    # For production, use a proper WSGI server like Gunicorn
    print("Starting app on port 5001...")
    app.run(debug=True, host='0.0.0.0', port=5001)