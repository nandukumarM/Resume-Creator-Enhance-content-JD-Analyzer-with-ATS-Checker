from app import app
import json
import os

def test_resume_render():
    with app.test_client() as client:
        # Create test file if not exists (although I already did)
        file_path = os.path.join(app.config['ANALYSIS_FOLDER'], 'gen_test123.json')
        if not os.path.exists(file_path):
            with open(file_path, 'w') as f:
                json.dump({
                    "personal_info": {"name": "Test", "contact_info": "test@test.com"},
                    "summary": "Summary",
                    "skills": {"technical": ["A"], "soft": ["B"]},
                    "experience": [],
                    "education": [],
                    "projects": []
                }, f)
        
        response = client.get('/generated-resume/test123')
        print(f"Status Code: {response.status_code}")
        if response.status_code != 200:
            print("Response Data (Error):")
            print(response.data.decode('utf-8'))
        else:
            print("Render Successful!")

if __name__ == "__main__":
    test_resume_render()
