from xhtml2pdf import pisa
from jinja2 import Environment, FileSystemLoader
import os

def test_bank_resume_generation():
    # Setup Jinja2 environment to render the template without running the full Flask app
    env = Environment(loader=FileSystemLoader('templates'))
    template = env.get_template('bank_resume.html')
    
    # Dummy data matching the user's image
    data = {
        'contact_info': {
            'name': 'UDAY KUMAR K S',
            'phone': '+91 8073472228',
            'email': 'udaykumar27ks@gmail.com',
            'location': 'Bangalore, India'
        },
        'professional_summary': 'I intend and want to work in a challenging environment where I can get opportunity and develop my technical skills and make best use of it for the growth of organization and myself.',
        'experience': [
            {
                'company': 'MYND Integrated Solutions Pvt. Ltd.',
                'client': 'TCPL-Bangalore US',
                'title': 'Analyst (Accounts Payable)',
                'duration': 'December 2023 to Till Date',
                'achievements': [
                    'Managed end to end P2P process to ensure compliance with company policy.',
                    'Effective management of AP team by proper work allocation.',
                    'Responsible for the timely completion of daily posting.',
                    'Processing Invoices like PO, Non-PO Invoices and Upload files.',
                    'Investigate the invoice discrepancies and follow up with clients.'
                ]
            }
        ],
        'education': [],
        'skills': {
            'erp_and_tools': ['SAP', 'Ms Origin', 'Tally ERP 9'],
            'domain_knowledge': ['Accounts Payable', 'Invoice Processing']
        }
    }
    
    # Render HTML
    html_content = template.render(**data)
    
    # Generate PDF
    with open('verify_bank_resume.pdf', "wb") as pdf_file:
        pisa_status = pisa.CreatePDF(html_content, dest=pdf_file)
        
    if pisa_status.err:
        print("FAILURE: PDF generation error")
    else:
        print("SUCCESS: verify_bank_resume.pdf generated successfully.")

if __name__ == "__main__":
    test_bank_resume_generation()
