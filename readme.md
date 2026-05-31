# Resume-Creator-Enhance-content-JD-Analyzer-with-ATS-Checker
# Resume Creator and ATS Checker

An intelligent web application designed to help job seekers create professional resumes tailored to specific Job Descriptions (JD). The application leverages AI to analyze resumes, score them against arbitrary JDs, and provide actionable feedback on missing keywords and skills, effectively acting as an ATS (Applicant Tracking System) simulator.

## ✨ Features

- **User Authentication**: Secure Login & Registration system to save and track your generated resumes.
- **Dynamic Resume Creation**: An intuitive builder to manually create a resume from scratch and export it to a well-formatted PDF.
- **Multiple Templates**: Choose between different professional templates (e.g., standard, bank format) for the generated PDF.
- **ATS Checking & Scoring**: Upload an existing resume (PDF) alongside a Job Description. Get an analysis that includes an ATS match score, missing skills, and detailed cultural fit clues.
- **AI Resume Enhancement**: Utilizes Groq LLM to intelligently recommend stronger resume bullet points and summaries based on the JD.
- **Tailored PDF Output**: Adjusts content and exports tailored versions of the resume directly into PDF format.
- **Personal Dashboard**: View your history and past analyses all in one place.

## 🛠️ Technology Stack

- **Backend framework**: Python, Flask, Werkzeug
- **AI Integration**: Groq API
- **PDF Processing**: PyMuPDF (PyMuPDF / fitz), reportlab, xhtml2pdf
- **Frontend**: HTML5, CSS3, JavaScript (with responsive/adaptive design elements)

## 🚀 Getting Started

Follow these steps to set up the project locally:

### 1. Prerequisites
- Python 3.8+ installed
- Git installed on your system

### 2. Clone the repository
```bash
git clone https://github.com/nandukumarM/Resume-Creator-Enhance-content-JD-Analyzer-with-ATS-Checker.git
cd Resume-Creator-Enhance-content-JD-Analyzer-with-ATS-Checker/"Resume Creator And ATS"/"Resume Creator"
```

### 3. Setup Virtual Environment (Optional but recommended)
```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Setup Environment Variables
Create a `.env` file in the root directory and add the following:
```env
GROQ_API_KEY=your_groq_api_key_here
SECRET_KEY=your_flask_secret_key_here
```
*(You can obtain a free API key from the Groq Developer console).*

### 6. Run the Application
You can run the provided batch script if on Windows:
```bash
run_app.bat
```
Alternatively, you can run the app directly using Python:
```bash
python app.py
```

Open your browser and navigate to `http://127.0.0.1:5000` to start using the application!

## 🧪 Testing

The project includes unit tests for verifying PDF generation, cleaning models, API handling, etc. Start tests via the provided test scripts:
```bash
# Example: Testing the Groq API connection and responses
python test_gemini.py 

# Example: Testing template selection functionality
python test_template_sel.py 

# Example: Run diagnostics if you encounter PDF formatting issues
python diagnose.py
```

## 📜 License

This project is intended for educational purposes and open-source contributions.
