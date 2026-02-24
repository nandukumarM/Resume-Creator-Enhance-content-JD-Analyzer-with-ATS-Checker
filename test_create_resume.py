import unittest
from app import app
import io

class TestResumeCreation(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_create_resume_with_new_sections(self):
        data = {
            'name': 'Test User',
            'email': 'test@example.com',
            'phone': '1234567890',
            'links': 'linkedin.com/in/test',
            'summary': 'Test Summary',
            'career_objective': 'To be a great engineer',
            'technical_skills': 'Python, Flask',
            'soft_skills': 'Communication, Teamwork',
            'languages': 'English, Hindi',
            'activities': 'Coding Club, Volunteer',
            'exp_title[]': ['Developer'],
            'exp_company[]': ['Tech Co'],
            'exp_dates[]': ['2020-Present'],
            'exp_desc[]': ['Built amazing things'],
            'edu_degree[]': ['B.Tech'],
            'edu_school[]': ['University'],
            'edu_dates[]': ['2016-2020'],
            'proj_name[]': ['Resume Builder'],
            'proj_tech[]': ['Python'],
            'proj_desc[]': ['A tool to build resumes'],
            'cert_name[]': ['Certified Python Dev'],
            'cert_auth[]': ['Python Institute'],
            'cert_year[]': ['2023']
        }

        response = self.app.post('/create', data=data, follow_redirects=True)
        
        # Check success
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/pdf')
        
        # Save PDF for manual inspection
        with open('test_resume_new_sections.pdf', 'wb') as f:
            f.write(response.data)
        print("Generated PDF saved as test_resume_new_sections.pdf")

if __name__ == '__main__':
    unittest.main()
