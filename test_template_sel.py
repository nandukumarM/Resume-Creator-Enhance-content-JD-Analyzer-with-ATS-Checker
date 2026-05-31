import unittest
from app import app
from flask import session

class TestResumeTemplateSelection(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        self.client = app.test_client()

    def test_create_resume_redirects_to_select(self):
        """Test that submitting the create form redirects to template selection."""
        data = {
            'name': 'John Doe',
            'email': 'john@example.com',
            'phone': '1234567890',
            'summary': 'Test Summary',
            'technical_skills': 'Python, Flask',
            'soft_skills': 'Communication',
            'exp_title[]': ['Developer'],
            'exp_company[]': ['Tech Co'],
            'exp_dates[]': ['2020-Present'],
            'exp_desc[]': ['Built stuff'],
            'edu_degree[]': ['BS'],
            'edu_school[]': ['University'],
            'edu_dates[]': ['2016-2020'],
            'edu_score[]': ['3.8'],
            'proj_name[]': ['Project A'],
            'proj_tech[]': ['Python'],
            'proj_desc[]': ['Did something'],
            'cert_name[]': ['Cert'],
            'cert_auth[]': ['Auth'],
            'cert_year[]': ['2021']
        }
        
        response = self.client.post('/create', data=data, follow_redirects=False)
        
        # Check redirect
        self.assertEqual(response.status_code, 302)
        self.assertTrue('/select-template' in response.location)
        
        # Check session data with a new request context or by checking the cookie/session handling?
        # In flask test client, we can access session inside a `with self.client:` block if we want, 
        # or rely on the next request to work.
        
        with self.client as c:
            c.post('/create', data=data)
            self.assertIn('resume_data', session)
            self.assertEqual(session['resume_data']['personal_info']['name'], 'John Doe')

    def test_select_template_page_loads(self):
        """Test that the selection page loads if session data exists."""
        with self.client as c:
            # Set session data
            with c.session_transaction() as sess:
                sess['resume_data'] = {'personal_info': {'name': 'Test'}}
            
            response = c.get('/select-template')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Choose Your Style', response.data)

    def test_select_template_redirects_if_no_session(self):
        """Test that selection page redirects to create if no session data."""
        response = self.client.get('/select-template')
        self.assertEqual(response.status_code, 302)
        self.assertTrue('/create' in response.location)

    def test_generate_resume_pdf(self):
        """Test that generating resume returns a PDF."""
        with self.client as c:
            # Set complicated session data to ensure PDF generation works
            resume_data = {
                'personal_info': {'name': 'John Doe', 'email': 'j@d.com', 'phone': '123', 'contact_info': 'j@d.com'},
                'summary': 'Summary',
                'skills': {'technical': ['Python'], 'soft': ['Teamwork']},
                'experience': [{'title': 'Dev', 'company': 'Co', 'dates': '2020', 'bullets': ['Work']}],
                'education': [{'degree': 'BS', 'school': 'Uni', 'dates': '2020'}],
                'projects': [],
                'certifications': []
            }
            with c.session_transaction() as sess:
                sess['resume_data'] = resume_data
            
            # Test Modern Template
            response = c.post('/generate-resume', data={'template_name': 'modern'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/pdf')
            self.assertIn(b'%PDF', response.data[:10])

            # Test Elegant Template
            response = c.post('/generate-resume', data={'template_name': 'elegant'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/pdf')

if __name__ == '__main__':
    unittest.main()
